"""Learn to autoland with limited sensors: domain-randomized, risk-averse Bayesian optimisation in SITL.

The aircraft has no airspeed sensor and no rangefinder, so landing quality depends on barometric flare timing,
throttle-only speed control and wind. We tune the ArduPlane landing parameters (+ glide slope) by flying the
REAL Cloudbreak landing sequence (hold -> commit -> final -> NAV_LAND) in headless SITL instances at 10x,
each trial under several randomized conditions (wind speed/direction/turbulence, baro drift, GPS noise), and
minimise CVaR_alpha (mean of the worst alpha-fraction of outcomes), not the mean -- we care about the bad tail.

Outputs (C:\\cb-data\\autoland):
  trials.jsonl          every landing: params, conditions, touchdown errors, sink rate, outcome
  learned_landing.parm  best parameter set (for SITL and, after gate F3, the real FC)
  dispersion.json       95 % touchdown envelope + rollout with the best params -> planner strip sizing

    python -m cloudbreak.ground.autoland.sitl_bo --instances 1 2 --trials 30 --conditions 3
Caveat: SITL's generic `plane` model is not a Tutor. sysid.py re-anchors ranges to real flight logs.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from cloudbreak.common.config import data_dir, site
from cloudbreak.common.geodesy import enu_offset
from cloudbreak.common.mav import GOVERNOR_SYSID, Link, mavlink
from cloudbreak.common.missions import LandingSpec, landing_items, takeoff_items, with_jump_back

OUT = Path(data_dir()) / "autoland"
OUT.mkdir(parents=True, exist_ok=True)
SPACE = dict(TECS_LAND_THR=(5.0, 45.0), TECS_LAND_SINK=(0.2, 1.0), LAND_FLARE_SEC=(1.0, 4.0),
             LAND_FLARE_ALT=(1.0, 5.0), LAND_PITCH_DEG=(-1.0, 6.0), glide_slope_pct=(8.0, 14.0))


class SimInstance:
    def __init__(self, i: int, speedup: float = 10.0):
        self.i = i
        self.port = 5762 + 10 * i
        cmd = ["wsl", "-d", "Ubuntu", "--", "env", f"SITL_INSTANCE={i}", f"SITL_SPEEDUP={speedup}",
               f"SITL_WORKDIR=/home/brian/sitl-run/bo{i}", "bash", "/mnt/c/dev/cloudbreak/sim/sitl/run_sitl.sh"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(8)
        self.link = Link(f"tcp:127.0.0.1:{self.port}", GOVERNOR_SYSID, role="rw", name=f"bo{i}")
        self.link.wait_heartbeat(90)
        self.speedup = speedup

    def set_params(self, d: dict):
        for k, v in d.items():
            self.link.send("param_set_send", self.link.ts, 1, k.encode(), float(v), mavlink.MAV_PARAM_TYPE_REAL32)
            time.sleep(0.02)
        time.sleep(0.5)

    def wall(self, sim_s):
        return sim_s / self.speedup

    def wait(self, pred, sim_timeout):
        t_end = time.monotonic() + self.wall(sim_timeout)
        while time.monotonic() < t_end:
            v = pred()
            if v:
                return v
            time.sleep(0.02)
        return None

    def fly(self, params: dict, cond: dict, home: tuple) -> dict:
        L = self.link
        hdg = cond["heading_deg"]
        self.set_params({k: v for k, v in params.items() if k.isupper()})
        self.set_params(dict(SIM_WIND_SPD=cond["wind_spd"], SIM_WIND_DIR=cond["wind_dir"], SIM_WIND_TURB=cond["turb"],
                             SIM_BARO_DRIFT=cond["baro_drift"], SIM_GPS1_NOISE=cond["gps_noise"]))
        spec = LandingSpec(touchdown_lat=home[0], touchdown_lon=home[1], heading_deg=hdg, touchdown_rel_alt_m=0.0,
                           approach_alt_m=20.0, short_final_alt_m=8.0, glide_slope_pct=params["glide_slope_pct"],
                           hold_alt_m=40.0, hold_radius_m=45.0, entry_radius_m=35.0, hold_offset_m=150.0)
        items = takeoff_items(40.0) + with_jump_back(landing_items(spec), base_seq=2)
        seq = {it.label: i + 1 for i, it in enumerate(items)}
        L.set_mode("FBWA")
        L.upload_mission(items)
        ok = False
        for _ in range(10):
            if L.command_long(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1, timeout=2) == 0:
                ok = True
                break
            time.sleep(self.wall(5))
        if not ok:
            return dict(outcome="arm_failed")
        L.set_mode("AUTO")
        cur = lambda: getattr(L.get("MISSION_CURRENT"), "seq", None)
        if not self.wait(lambda: cur() == seq["hold"], 400):
            return dict(outcome="no_hold")
        self.wait(lambda: False, 15)
        L.set_current(seq["entry"])
        touch, max_bounce, vz_td, gs_td = None, 0.0, None, None
        t_end = time.monotonic() + self.wall(400)
        while time.monotonic() < t_end:
            g = L.get("GLOBAL_POSITION_INT")
            s = cur()
            if s == seq["goaround"] or s == seq["hold"] and touch is None and g and g.relative_alt > 15000:
                if s == seq["goaround"]:
                    return dict(outcome="go_around")
            if g is not None and s == seq["touchdown"]:
                ra = g.relative_alt / 1000.0
                if touch is None and ra < 0.25:
                    touch = (g.lat / 1e7, g.lon / 1e7)
                    vz_td = g.vz / 100.0
                    gs_td = math.hypot(g.vx, g.vy) / 100.0
                    t_touch = time.monotonic()
                elif touch is not None:
                    max_bounce = max(max_bounce, ra)
                    if math.hypot(g.vx, g.vy) < 50 or time.monotonic() - t_touch > self.wall(40):
                        break
            time.sleep(0.01)
        if touch is None:
            return dict(outcome="no_touchdown")
        g = L.get("GLOBAL_POSITION_INT")
        rest = (g.lat / 1e7, g.lon / 1e7)
        h = math.radians(hdg)
        de, dn = enu_offset(home[0], home[1], *touch)
        along, cross = de * math.sin(h) + dn * math.cos(h), de * math.cos(h) - dn * math.sin(h)
        de2, dn2 = enu_offset(touch[0], touch[1], *rest)
        rollout = math.hypot(de2, dn2)
        # wait for auto-disarm so the next trial starts clean
        self.wait(lambda: not (L.get("HEARTBEAT").base_mode & 128), 60)
        return dict(outcome="landed", along_m=along, cross_m=cross, vz_td=vz_td, gs_td=gs_td, bounce_m=max_bounce,
                    rollout_m=rollout)


def cost(r: dict) -> float:
    if r.get("outcome") != "landed":
        return 10.0
    c = abs(r["along_m"]) / 15.0 + abs(r["cross_m"]) / 4.0
    c += max(0.0, r["vz_td"] - 0.8) * 4.0          # hard landing (sink > 0.8 m/s)
    c += max(0.0, r["bounce_m"] - 0.3) * 3.0       # bounce / balloon
    return float(c)


def cvar(xs, alpha=0.34):
    xs = sorted(xs, reverse=True)
    k = max(1, int(math.ceil(alpha * len(xs))))
    return float(np.mean(xs[:k]))


def sample_conditions(rng, n, fc=None):
    out = []
    for _ in range(n):
        spd = float(rng.uniform(0, 7))
        hdg = float(rng.uniform(0, 360))
        rel = float(rng.normal(0, 35))                # mostly into wind, some crosswind
        out.append(dict(heading_deg=round(hdg, 1), wind_spd=round(spd, 2), wind_dir=round((hdg + rel) % 360, 1),
                        turb=round(float(rng.uniform(0, 1.5)), 2), baro_drift=round(float(rng.normal(0, 0.004)), 5),
                        gps_noise=round(float(rng.uniform(0.2, 1.0)), 2)))
    return out


def main(argv=None):
    import optuna

    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", type=int, nargs="+", default=[1, 2])
    ap.add_argument("--trials", type=int, default=30)
    ap.add_argument("--conditions", type=int, default=3)
    ap.add_argument("--speedup", type=float, default=10.0)
    a = ap.parse_args(argv)
    s = site()["site"]
    home = (s["center_lat"], s["center_lon"])
    sims = [SimInstance(i, a.speedup) for i in a.instances]
    print(f"[bo] {len(sims)} SITL instances up", flush=True)
    for sim in sims:   # baseline tutor-like extras
        sim.set_params(dict(SIM_SPEEDUP=a.speedup))
    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=7, multivariate=True))
    study.enqueue_trial(dict(TECS_LAND_THR=30.0, TECS_LAND_SINK=0.3, LAND_FLARE_SEC=2.0, LAND_FLARE_ALT=3.0,
                             LAND_PITCH_DEG=2.0, glide_slope_pct=12.0))       # the hand-set starting point
    rng = np.random.default_rng(11)
    log = open(OUT / "trials.jsonl", "a")
    lock = threading.Lock()

    def objective_on(sim):
        def obj(trial):
            params = {k: trial.suggest_float(k, *v) for k, v in SPACE.items()}
            conds = sample_conditions(rng, a.conditions)
            costs = []
            for cond in conds:
                try:
                    r = sim.fly(params, cond, home)
                except Exception as e:
                    r = dict(outcome=f"error {e!r}")
                c = cost(r)
                costs.append(c)
                with lock:
                    log.write(json.dumps(dict(t=time.time(), trial=trial.number, inst=sim.i, params=params, cond=cond, result=r, cost=c)) + "\n")
                    log.flush()
            v = cvar(costs)
            print(f"[bo] trial {trial.number} inst {sim.i} CVaR {v:.2f} costs {[round(c, 2) for c in costs]}", flush=True)
            return v
        return obj

    per = max(1, a.trials // len(sims))
    threads = [threading.Thread(target=lambda sim=sim: study.optimize(objective_on(sim), n_trials=per)) for sim in sims]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    best = study.best_params
    (OUT / "learned_landing.parm").write_text("# learned by sitl_bo.py (CVaR over randomized conditions)\n" +
                                              "".join(f"{k} {v:.3f}\n" for k, v in best.items() if k.isupper()))
    write_dispersion(best)
    print("[bo] best", best, "CVaR", study.best_value, flush=True)


def write_dispersion(best: dict | None = None):
    """95 % touchdown envelope from landings flown with near-best parameters."""
    rows = [json.loads(l) for l in open(OUT / "trials.jsonl")]
    if best:
        rows = [r for r in rows if all(abs(r["params"][k] - best[k]) < 1e-6 for k in best)] or rows
    landed = [r["result"] for r in rows if r["result"].get("outcome") == "landed"]
    if len(landed) < 3:
        return None
    al = np.array([r["along_m"] for r in landed])
    cr = np.array([r["cross_m"] for r in landed])
    ro = np.array([r["rollout_m"] for r in landed])
    d = dict(touchdown_disp_long_m=round(float(np.percentile(np.abs(al - np.median(al)), 95) + abs(np.median(al))), 1),
             touchdown_disp_lat_m=round(float(np.percentile(np.abs(cr), 95)), 1),
             rollout_m=round(float(np.percentile(ro, 95)), 1), n=len(landed),
             success_rate=round(len(landed) / max(1, len(rows)), 2),
             note="SITL generic plane model; re-anchor with sysid.py on real logs before trusting absolute values")
    (OUT / "dispersion_sitl.json").write_text(json.dumps(d, indent=1))
    return d


if __name__ == "__main__":
    main()
