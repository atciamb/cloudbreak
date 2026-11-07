"""Verify the ArduPlane 4.7.2 SITL behaviours Cloudbreak's governor depends on.

Prereq: SITL running via sim/sitl/run_sitl.ps1 (tutor_like.parm). Ports: 5762 governor, 5763 core, 5765 sim pilot.
Run:    .venv\\Scripts\\python sim\\sitl\\verify_sitl.py [--speedup 4]
Writes: C:\\cb-data\\sitl_verify\\<stamp>.json and prints a pass/fail table.

The "sim pilot" link stands in for the human pilot's RC (arming, throttle-up abort). It is SITL-only:
the real aircraft is armed by the pilot and the governor never sends RC overrides or arm commands.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from cloudbreak.common.config import data_dir, site
from cloudbreak.common.geodesy import enu_offset
from cloudbreak.common.mav import (GOVERNOR_SYSID, CORE_SYSID, Link, MissionItem, install_signing_key, load_key,
                                   mavlink, mission_hash)
from cloudbreak.common.missions import LandingSpec, landing_items, takeoff_items, with_jump_back

RESULTS: dict[str, dict] = {}


def record(name, ok, **ev):
    RESULTS[name] = dict(ok=bool(ok), **ev)
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {json.dumps(ev, default=str)[:300]}", flush=True)


class Clock:
    def __init__(self, speedup):
        self.s = speedup

    def sleep(self, sim_s):
        time.sleep(sim_s / self.s)

    def wall(self, sim_s):
        return sim_s / self.s


def wait_until(pred, sim_timeout, clk: Clock, poll=0.1):
    t_end = time.monotonic() + clk.wall(sim_timeout)
    while time.monotonic() < t_end:
        v = pred()
        if v:
            return v
        time.sleep(poll)
    return None


def cur_seq(core: Link):
    m = core.get("MISSION_CURRENT")
    return None if m is None else m.seq


def rel_alt(core: Link):
    m = core.get("GLOBAL_POSITION_INT")
    return None if m is None else m.relative_alt / 1000.0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--speedup", type=float, default=4.0)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--wind-spd", type=float, default=3.0)
    ap.add_argument("--wind-dir", type=float, default=200.0)
    a = ap.parse_args(argv)
    clk = Clock(a.speedup)
    key = load_key("sitl")

    gov = Link(f"tcp:{a.host}:5762", GOVERNOR_SYSID, role="rw", name="governor")
    core = Link(f"tcp:{a.host}:5763", CORE_SYSID, role="ro", name="core")
    pilot = Link(f"tcp:{a.host}:5765", GOVERNOR_SYSID, compid=191, role="ro", name="sim_pilot")
    for l in (gov, core, pilot):
        l.wait_heartbeat(60)
    print("links up; autopilot sysid", gov.target_system, flush=True)

    # ---------------------------------------------------------------- pre-flight setup (unsigned, SITL only)
    for pname, val in [("SIM_SPEEDUP", a.speedup), ("SIM_WIND_SPD", a.wind_spd), ("SIM_WIND_DIR", a.wind_dir),
                       ("SIM_WIND_TURB", 0.5)]:
        gov.send("param_set_send", gov.ts, 1, pname.encode(), float(val), mavlink.MAV_PARAM_TYPE_REAL32)
    time.sleep(1.0)

    # ---------------------------------------------------------------- E1 signing
    req = mavlink.MAV_CMD_REQUEST_MESSAGE
    base = core.command_long(req, mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION, timeout=2)
    install_signing_key(gov, key)
    time.sleep(1.0)
    gov.m.setup_signing(key, sign_outgoing=True)
    pilot.m.setup_signing(key, sign_outgoing=True)
    time.sleep(1.0)
    unsigned = core.command_long(req, mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION, timeout=2, retries=1)
    signed = gov.command_long(req, mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION, timeout=2)
    telem_age = core.age("ATTITUDE")
    record("E1_signing", base == 0 and unsigned is None and signed == 0 and telem_age < 1.0,
           unsigned_before_key=base, unsigned_after_key=unsigned, signed_after_key=signed,
           unsigned_reader_attitude_age_s=round(telem_age, 2))

    # ---------------------------------------------------------------- wait for GPS / EKF
    ok = wait_until(lambda: (core.get("GPS_RAW_INT") and core.get("GPS_RAW_INT").fix_type >= 3
                             and core.get("EKF_STATUS_REPORT") and (core.get("EKF_STATUS_REPORT").flags & 0x10)), 120, clk)
    record("gps_ekf_ready", ok, fix=getattr(core.get("GPS_RAW_INT"), "fix_type", None))

    # ---------------------------------------------------------------- mission build / upload / read-back
    s = site()["site"]
    hdg = a.wind_dir % 360.0  # land into wind: travel toward where the wind comes from
    spec = LandingSpec(touchdown_lat=s["center_lat"], touchdown_lon=s["center_lon"], heading_deg=hdg,
                       touchdown_rel_alt_m=0.0)
    pre = takeoff_items(40.0)
    land = landing_items(spec)
    items = pre + with_jump_back(land, base_seq=1 + len(pre))
    seq = {it.label: i + 1 for i, it in enumerate(items)}
    gov.upload_mission(items)
    back = gov.download_mission()
    h1, h2 = mission_hash(items), mission_hash(back)
    record("E2_upload_readback_hash", h1 == h2 and len(back) == len(items), n=len(items), hash=h1[:16], readback=h2[:16])

    # ---------------------------------------------------------------- arm + AUTO (sim pilot arms; real pilot does this)
    gov.set_mode("FBWA")
    t0 = time.monotonic()
    arm = None
    for _ in range(20):
        arm = pilot.command_long(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1, timeout=2)
        if arm == 0:
            break
        clk.sleep(3)
    record("arm", arm == 0, result=arm, statustext=getattr(core.get("STATUSTEXT"), "text", None))
    if arm != 0:
        return finish()
    gov.set_mode("AUTO")
    got_hold = wait_until(lambda: cur_seq(core) == seq["hold"], 240, clk)
    record("reach_hold", got_hold, seq=cur_seq(core), alt=rel_alt(core))

    # E3 the hold really holds
    clk.sleep(30)
    record("E3_hold_holds", cur_seq(core) == seq["hold"], seq=cur_seq(core), alt=rel_alt(core),
           mode=core.flightmode())

    # E4 governor heartbeat loss during hold -> RTL after FS_LONG_TIMEOUT (20 s)
    gov.pause_heartbeat(True)
    t_loss = time.monotonic()
    rtl = wait_until(lambda: core.flightmode() == "RTL", 40, clk)
    record("E4_gcs_failsafe_in_hold_rtl", bool(rtl), mode=core.flightmode(),
           sim_s_to_rtl=round((time.monotonic() - t_loss) * a.speedup, 1))
    gov.pause_heartbeat(False)
    clk.sleep(3)
    gov.set_mode("AUTO")
    gov.set_current(seq["hold"])
    wait_until(lambda: cur_seq(core) == seq["hold"], 30, clk)
    clk.sleep(20)

    # E5 commit: jump out of the hold
    committed = gov.set_current(seq["entry"])
    adv = wait_until(lambda: (cur_seq(core) or 0) >= seq["final1"], 180, clk)
    record("E5_commit_breaks_hold", committed and bool(adv), seq=cur_seq(core))

    # E6 DO_GO_AROUND on NAV_LAND
    on_land = wait_until(lambda: cur_seq(core) == seq["touchdown"] and (rel_alt(core) or 99) < 15, 240, clk)
    alt_at = rel_alt(core)
    res = gov.command_long(mavlink.MAV_CMD_DO_GO_AROUND, 30) if on_land else None
    climbed = wait_until(lambda: cur_seq(core) == seq["goaround"] or ((rel_alt(core) or 0) > (alt_at or 0) + 8), 60, clk)
    back_hold = wait_until(lambda: cur_seq(core) == seq["hold"], 240, clk)
    record("E6_do_go_around", bool(on_land and climbed and back_hold), ack=res, alt_at_cmd=alt_at,
           seq_after=cur_seq(core))

    # E7 pilot throttle > 90 % on NAV_LAND aborts (LAND_ABORT_THR=1)
    clk.sleep(10)
    gov.set_current(seq["entry"])
    on_land = wait_until(lambda: cur_seq(core) == seq["touchdown"] and (rel_alt(core) or 99) < 12, 300, clk)
    alt_at = rel_alt(core)
    if on_land:
        for _ in range(int(max(4, 2 * a.speedup))):
            pilot.send("rc_channels_override_send", pilot.ts, 1, 0, 0, 1950, 0, 0, 0, 0, 0)
            time.sleep(0.25)
        pilot.send("rc_channels_override_send", pilot.ts, 1, 0, 0, 0, 0, 0, 0, 0, 0)
    climbed = wait_until(lambda: cur_seq(core) == seq["goaround"] or ((rel_alt(core) or 0) > (alt_at or 0) + 8), 60, clk)
    back_hold = wait_until(lambda: cur_seq(core) == seq["hold"], 240, clk)
    record("E7_throttle_abort", bool(on_land and climbed and back_hold), alt_at_override=alt_at, seq_after=cur_seq(core))

    # E8 link loss after commit -> landing continues; measure touchdown
    clk.sleep(10)
    t_land_start = time.monotonic()
    gov.set_current(seq["entry"])
    wait_until(lambda: cur_seq(core) == seq["final2"], 300, clk)
    gov.pause_heartbeat(True)
    touch = None
    t_end = time.monotonic() + clk.wall(240)
    while time.monotonic() < t_end:
        g = core.get("GLOBAL_POSITION_INT")
        if g is not None and g.relative_alt < 300 and cur_seq(core) == seq["touchdown"]:
            touch = (g.lat / 1e7, g.lon / 1e7, g.relative_alt / 1000, math.hypot(g.vx, g.vy) / 100, g.vz / 100)
            break
        time.sleep(0.05)
    stopped = wait_until(lambda: (core.get("GLOBAL_POSITION_INT") and
                                  math.hypot(core.get("GLOBAL_POSITION_INT").vx, core.get("GLOBAL_POSITION_INT").vy) < 50
                                  and core.get("GLOBAL_POSITION_INT").relative_alt < 1500), 120, clk)
    g = core.get("GLOBAL_POSITION_INT")
    rest = (g.lat / 1e7, g.lon / 1e7)
    mode_after = core.flightmode()
    gov.pause_heartbeat(False)
    ev = dict(mode_after=mode_after, wall_s_commit_to_stop=round(time.monotonic() - t_land_start, 1))
    if touch:
        de, dn = enu_offset(spec.touchdown_lat, spec.touchdown_lon, touch[0], touch[1])
        h = math.radians(spec.heading_deg)
        ev.update(touch_along_m=round(de * math.sin(h) + dn * math.cos(h), 1),
                  touch_cross_m=round(de * math.cos(h) - dn * math.sin(h), 1),
                  touch_groundspeed=round(touch[3], 2), touch_vz=round(touch[4], 2))
        de, dn = enu_offset(spec.touchdown_lat, spec.touchdown_lon, rest[0], rest[1])
        ev.update(rest_along_m=round(de * math.sin(h) + dn * math.cos(h), 1),
                  rest_cross_m=round(de * math.cos(h) - dn * math.sin(h), 1))
    record("E8_linkloss_after_commit_lands", bool(touch and stopped and mode_after == "AUTO"), **ev)
    return finish()


def finish():
    out = Path(data_dir()) / "sitl_verify"
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"verify_{time.strftime('%Y%m%dT%H%M%S')}.json"
    p.write_text(json.dumps(RESULTS, indent=1, default=str))
    print("wrote", p)
    return 0 if RESULTS and all(r["ok"] for r in RESULTS.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
