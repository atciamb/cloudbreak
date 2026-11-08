"""SITL check that a governed landing pattern flies INSIDE a site's geofence (SITL physics, not the real Tutor).

    # SITL homed in the site (flat SITL ground at home altitude), then the SITL signing key:
    wsl -d Ubuntu -- env SITL_SPEEDUP=4 SITL_HOME=42.70512,-73.71078,6,85 bash /mnt/c/dev/cloudbreak/sim/sitl/run_sitl.sh
    .venv\\Scripts\\python sim\\sitl\\setup_signing.py
    .venv\\Scripts\\python sim\\sitl\\fit_check_sitl.py --site schuyler --td 42.70542,-73.70982 --hdg 85

It builds the pattern exactly as the planner does (config/aircraft_tutor.toml [landing]), uploads it with the site's
fence, and flies: takeoff -> hold -> last look -> hold -> commit -> DO_GO_AROUND on short final -> hold -> commit -> land.
The fence (polygon, FENCE_ACTION=RTL) is enabled once the plane is in the hold, so a breach would show as RTL.
Reports the minimum distance inside the fence along the whole flown track, breaches, and the touchdown point.
Evidence: C:\\cb-data\\sitl_verify\\fitcheck_<time>.json (+ .png track over the ortho).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shapely.geometry import Point  # noqa: E402

from cloudbreak.common.config import data_dir, set_site, site  # noqa: E402
from cloudbreak.common.fence import check_path, site_fence  # noqa: E402
from cloudbreak.common.geodesy import enu_offset, lonlat_to_utm  # noqa: E402
from cloudbreak.common.mav import CORE_SYSID, GOVERNOR_SYSID, Link, load_key, mavlink, mission_hash  # noqa: E402
from cloudbreak.common.missions import landing_items, landing_path_points, takeoff_items, with_jump_back  # noqa: E402
from cloudbreak.common.config import load_toml  # noqa: E402
from cloudbreak.ground.core.planner.strips import load_aircraft, make_spec, required_dims  # noqa: E402
from cloudbreak.ground.governor.approach import GateConfig, approach_state, gate_violation, look_start_ok  # noqa: E402

EV: dict = {}


def record(name, ok, **info):
    EV[name] = dict(ok=bool(ok), **info)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {json.dumps(info, default=str)}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--td", required=True, help="touchdown lat,lon (from the planner)")
    ap.add_argument("--hdg", type=float, required=True, help="landing heading (deg true)")
    ap.add_argument("--side", type=int, default=-1, help="circuit side: -1 left, +1 right (from the planner)")
    ap.add_argument("--speedup", type=float, default=4.0)
    ap.add_argument("--wind-spd", type=float, default=1.0)
    ap.add_argument("--wind-dir", type=float, default=90.0, help="direction the wind comes FROM")
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args(argv)
    set_site(a.site)
    fence = site_fence(site())
    if fence is None:
        raise SystemExit(f"site {a.site} has no fence")
    td_lat, td_lon = (float(v) for v in a.td.split(","))
    cfg = load_aircraft()
    Lc = cfg["landing"]
    L = required_dims(cfg)[0]
    spec = make_spec(Lc, L, td_lat, td_lon, a.hdg, 0.0, side=a.side)   # SITL ground is flat at home altitude
    model = check_path(landing_path_points(spec, Lc["missed_climb_gradient"]), fence)
    print(f"pattern: {json.dumps(spec.to_dict())}\nmodelled fence margin {model.worst_margin_m:.1f} m ({model.reason})")
    wall = lambda sim_s: sim_s / a.speedup                    # noqa: E731

    key = load_key("sitl")
    gov = Link(f"tcp:{a.host}:5762", GOVERNOR_SYSID, key=key, role="rw", name="governor")
    core = Link(f"tcp:{a.host}:5763", CORE_SYSID, role="ro", name="core")
    pilot = Link(f"tcp:{a.host}:5765", GOVERNOR_SYSID, compid=191, key=key, role="ro", name="sim_pilot")
    for l in (gov, core, pilot):
        l.wait_heartbeat(60)
    if gov.get_param("SIM_SPEEDUP") is None:
        raise SystemExit("refusing: not SITL")

    def setp(name, val):
        t = time.perf_counter()
        gov.send("param_set_send", gov.ts, 1, name.encode(), float(val), mavlink.MAV_PARAM_TYPE_REAL32)
        gov.wait("PARAM_VALUE", lambda m: m.param_id == name, timeout=3, since=t)

    for k, v in dict(SIM_SPEEDUP=a.speedup, SIM_WIND_SPD=a.wind_spd, SIM_WIND_DIR=a.wind_dir, SIM_WIND_TURB=0.5,
                     FENCE_ENABLE=0, FENCE_TYPE=5, FENCE_ACTION=1, FENCE_ALT_MAX=fence.alt_max_m, FENCE_OPTIONS=0,
                     FENCE_RET_ALT=50, RTL_ALTITUDE=50).items():
        setp(k, v)

    pre = takeoff_items(30.0)
    items = pre + with_jump_back(landing_items(spec), base_seq=1 + len(pre))
    seq = {it.label: i + 1 for i, it in enumerate(items)}
    gov.upload_mission(items)
    record("upload_readback", mission_hash(gov.download_mission()) == mission_hash(items), n=len(items))
    gov.upload_fence_polygon(fence.polygon_latlon)
    time.sleep(2)
    nf = len(gov.download_mission(mission_type=mavlink.MAV_MISSION_TYPE_FENCE))
    record("fence_uploaded", nf == len(fence.polygon_latlon), vertices=nf)

    cur = lambda: getattr(core.get("MISSION_CURRENT"), "seq", None)                                    # noqa: E731
    alt = lambda: (core.get("GLOBAL_POSITION_INT").relative_alt / 1000) if core.get("GLOBAL_POSITION_INT") else None  # noqa: E731

    def wait(pred, sim_timeout):
        end = time.monotonic() + wall(sim_timeout)
        while time.monotonic() < end:
            if pred():
                return True
            time.sleep(0.1)
        return False

    track: list = []
    modes: list = []
    stop = threading.Event()

    def recorder():
        last_mode = None
        while not stop.is_set():
            g = core.get("GLOBAL_POSITION_INT")
            if g is not None:
                track.append((g.lat / 1e7, g.lon / 1e7, g.relative_alt / 1000, cur(), time.monotonic()))
            m = core.flightmode()
            if m != last_mode:
                modes.append((m, cur(), time.monotonic()))
                last_mode = m
            time.sleep(0.1)

    ok = wait(lambda: core.get("GPS_RAW_INT") and core.get("GPS_RAW_INT").fix_type >= 3 and core.get("EKF_STATUS_REPORT")
              and core.get("EKF_STATUS_REPORT").flags & 0x10, 180)
    record("gps_ekf_ready", ok)
    gov.set_mode("FBWA")
    arm = None
    for _ in range(20):
        arm = pilot.command_long(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1, timeout=2)
        if arm == 0:
            break
        time.sleep(wall(3))
    record("arm", arm == 0, result=arm, statustext=getattr(core.get("STATUSTEXT"), "text", None))
    if arm != 0:
        return finish(a, fence, spec, track, modes, model)
    gov.set_mode("AUTO")
    hold_it = next(i for i in items if i.label == "hold")

    def on_hold_circle():
        g = core.get("GLOBAL_POSITION_INT")
        if g is None or cur() != seq["hold"]:
            return False
        de, dn = enu_offset(hold_it.lat, hold_it.lon, g.lat / 1e7, g.lon / 1e7)
        return abs(math.hypot(de, dn) - spec.hold_radius_m) < 20 and g.relative_alt / 1000 > spec.hold_alt_m - 6

    # (SITL auto-takeoff and its turn back are not part of the real flow: the pilot flies the Tutor to the area)
    def steady_on_circle(sim_s=25.0):
        """on the hold circle continuously for sim_s seconds (not just crossing it during the join)"""
        end = time.monotonic() + wall(600)
        since = None
        while time.monotonic() < end:
            if on_hold_circle():
                since = since or time.monotonic()
                if time.monotonic() - since >= wall(sim_s):
                    return True
            else:
                since = None
            time.sleep(0.1)
        return False

    record("reach_hold", steady_on_circle(), seq=cur(), alt=alt())
    setp("FENCE_ENABLE", 1)
    threading.Thread(target=recorder, daemon=True).start()
    time.sleep(wall(60))                                    # a few hold orbits (measured below)

    # last look, started at the tangent point exactly as the governor does, then back to the hold
    def at_tangent():
        g = core.get("GLOBAL_POSITION_INT")
        return g is not None and cur() == seq["hold"] and look_start_ok(spec.to_dict(), g.lat / 1e7, g.lon / 1e7, g.vx / 100, g.vy / 100)
    armed_ok = wait(at_tangent, 200)
    gov.set_current(seq["look_a"])
    looked = armed_ok and wait(lambda: (cur() or 0) >= seq["look_b"], 120) and wait(lambda: cur() == seq["hold"], 200)
    record("last_look_and_back_to_hold", looked, started_at_tangent=armed_ok, seq=cur())
    time.sleep(wall(20))

    gate = GateConfig(**load_toml("aircraft_tutor.toml").get("approach_gate", {}))
    sd = spec.to_dict()

    def final_with_gate(force_go_around_below: float | None):
        """Fly one final from the commit, applying the governor's stabilized-approach gate below the decision point.
        Returns ('landed'|'gate_go_around'|'forced_go_around'|'timeout', worst gate numbers)."""
        worst = dict(max_abs_xtrack_m=0.0, max_abs_track_err_deg=0.0, max_abs_height_err_m=0.0)
        end = time.monotonic() + wall(400)
        while time.monotonic() < end:
            g = core.get("GLOBAL_POSITION_INT")
            if cur() == seq["touchdown"] and g is not None:
                st = approach_state(sd, g.lat / 1e7, g.lon / 1e7, g.relative_alt / 1000, g.vx / 100, g.vy / 100)
                gs = math.hypot(g.vx, g.vy) / 100
                worst["max_abs_xtrack_m"] = round(max(worst["max_abs_xtrack_m"], abs(st.cross_m)), 1)
                if st.height_above_td_m > gate.flare_alt_m:
                    if st.track_err_deg is not None and gs > gate.min_groundspeed_mps:
                        worst["max_abs_track_err_deg"] = round(max(worst["max_abs_track_err_deg"], abs(st.track_err_deg)), 1)
                    worst["max_abs_height_err_m"] = round(max(worst["max_abs_height_err_m"], abs(st.height_err_m)), 1)
                why = gate_violation(st, gs, gate)
                if why is not None:
                    gov.command_long(mavlink.MAV_CMD_DO_GO_AROUND, spec.abort_alt_m)
                    worst["gate_reason"] = why
                    return "gate_go_around", worst
                if force_go_around_below is not None and st.height_above_td_m < force_go_around_below:
                    gov.command_long(mavlink.MAV_CMD_DO_GO_AROUND, spec.abort_alt_m)
                    return "forced_go_around", worst
                if g.relative_alt < 1500 and gs < 0.5:
                    return "landed", worst
            time.sleep(0.05)
        return "timeout", worst

    # commit, forced go-around on short final (8 m), back to the hold
    gov.set_current(seq["entry"])
    out, worst = final_with_gate(8.0)
    climbed = wait(lambda: (alt() or 0) > 18, 90) if out != "timeout" else False
    back = wait(lambda: cur() == seq["hold"], 300)
    record("go_around_and_back_to_hold", out in ("forced_go_around", "gate_go_around") and climbed and back,
           outcome=out, gate=worst, seq=cur())
    time.sleep(wall(20))

    # commit and land (up to max_unstable attempts, like the governor; then it would be a manual landing)
    landed, attempts, worsts = False, 0, []
    while attempts < gate.max_unstable and not landed:
        attempts += 1
        gov.set_current(seq["entry"])
        out, worst = final_with_gate(None)
        worsts.append(dict(outcome=out, **worst))
        if out == "landed":
            landed = True
        elif out == "gate_go_around":
            wait(lambda: cur() == seq["hold"], 300)
            time.sleep(wall(10))
        else:
            break
    record("approach_gate_stable", landed and attempts == 1, attempts=attempts, finals=worsts,
           would_be="autoland" if landed else "MANUAL LANDING (gate)")
    time.sleep(wall(5))
    g = core.get("GLOBAL_POSITION_INT")
    de, dn = enu_offset(td_lat, td_lon, g.lat / 1e7, g.lon / 1e7)
    h = math.radians(a.hdg)
    along, cross = de * math.sin(h) + dn * math.cos(h), de * math.cos(h) - dn * math.sin(h)
    W = required_dims(cfg)[1]
    th_along, end_along = -Lc["aim_fraction"] * L, (1 - Lc["aim_fraction"]) * L
    on_strip = th_along <= along <= end_along and abs(cross) <= W / 2
    record("landed_on_strip", landed and on_strip, rest_along_m=round(along, 1), rest_cross_m=round(cross, 1),
           strip_along_m=[round(th_along, 1), round(end_along, 1)], strip_half_width_m=round(W / 2, 1),
           mode=core.flightmode())
    stop.set()
    fs = core.get("FENCE_STATUS")
    record("no_fence_breach", (fs is None or fs.breach_count == 0) and not any(m == "RTL" for m, _, _ in modes),
           breach_count=None if fs is None else fs.breach_count, modes=[m for m, _, _ in modes])
    return finish(a, fence, spec, track, modes, model)


def finish(a, fence, spec, track, modes, model) -> int:
    poly = fence.utm_polygon()
    flown = [(la, lo) for la, lo, al, sq, t in track if al > 2.0]          # airborne part
    margins = [poly.exterior.distance(Point(*lonlat_to_utm(lo, la))) * (1 if poly.contains(Point(*lonlat_to_utm(lo, la))) else -1)
               for la, lo in flown]
    worst = min(margins) if margins else None
    if margins:
        i = margins.index(worst)
        record("flown_track_inside_fence", worst >= 0, min_margin_m=round(worst, 1), at=flown[i],
               modelled_margin_m=round(model.worst_margin_m, 1), points=len(flown))
    import numpy as np
    hold_xy = np.array([lonlat_to_utm(lo, la) for la, lo, al, sq, t in track if sq == 2 and al > 30])
    if len(hold_xy) > 20:
        cx, cy = lonlat_to_utm(*reversed(_hold_center(spec)))
        r = np.hypot(hold_xy[:, 0] - cx, hold_xy[:, 1] - cy)
        record("hold_radius_as_flown", float(np.median(r)) <= max(spec.turn_radius_m, spec.hold_radius_m) * 1.1,
               median_m=round(float(np.median(r)), 1), commanded_m=spec.hold_radius_m,
               modelled_flown_m=spec.turn_radius_m)
    out = data_dir() / "sitl_verify"
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    p = out / f"fitcheck_{a.site}_{stamp}.json"
    p.write_text(json.dumps(dict(site=a.site, spec=spec.to_dict(), wind=dict(spd=a.wind_spd, dir=a.wind_dir), events=EV,
                                 track=[t[:4] for t in track], modes=modes), indent=1, default=str))
    try:
        plot(a.site, fence, spec, track, out / f"fitcheck_{a.site}_{stamp}.png")
    except Exception as e:                                                   # noqa: BLE001
        print("plot skipped:", e)
    allok = all(v["ok"] for v in EV.values())
    print(f"\n{'ALL PASS' if allok else 'SOME CHECKS FAILED'} -> {p}")
    return 0 if allok else 1


def _hold_center(spec):
    it = next(i for i in landing_items(spec) if i.label == "hold")
    return it.lat, it.lon


def plot(site_key, fence, spec, track, path):
    import numpy as np
    import rasterio
    from PIL import Image, ImageDraw
    from rasterio.windows import from_bounds

    from cloudbreak.common.config import priors_dir

    xs, ys = zip(*[lonlat_to_utm(lo, la) for la, lo in fence.polygon_latlon])
    pad = 120
    B = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    Wp = 1000
    Hp = int(Wp * (B[3] - B[1]) / (B[2] - B[0]))
    with rasterio.open(Path(priors_dir()) / "layers" / "ortho_rgb.tif") as src:
        arr = src.read([1, 2, 3], window=from_bounds(*B, transform=src.transform), out_shape=(3, Hp, Wp))
    img = Image.fromarray(np.transpose(arr, (1, 2, 0)).astype(np.uint8)).convert("RGB")
    dr = ImageDraw.Draw(img)
    px = lambda x, y: ((x - B[0]) / (B[2] - B[0]) * Wp, (B[3] - y) / (B[3] - B[1]) * Hp)   # noqa: E731
    dr.line([px(x, y) for x, y in list(zip(xs, ys)) + [(xs[0], ys[0])]], fill=(255, 0, 255), width=4)
    model = [px(*lonlat_to_utm(lo, la)) for la, lo, _ in landing_path_points(spec)]
    for q in model:
        dr.point(q, fill=(0, 255, 255))
    pts = [px(*lonlat_to_utm(lo, la)) for la, lo, al, sq, t in track]
    if len(pts) > 1:
        dr.line(pts, fill=(255, 255, 0), width=2)
    x, y = px(*lonlat_to_utm(spec.touchdown_lon, spec.touchdown_lat))
    dr.ellipse([x - 6, y - 6, x + 6, y + 6], outline=(255, 255, 255), width=3)
    dr.line([(20, Hp - 20), (20 + 100 / (B[2] - B[0]) * Wp, Hp - 20)], fill=(255, 255, 255), width=5)
    dr.text((20, Hp - 40), "100 m   magenta: fence   cyan: modelled path   yellow: SITL track", fill=(255, 255, 255))
    img.save(path)
    print("plot:", path)


if __name__ == "__main__":
    raise SystemExit(main())
