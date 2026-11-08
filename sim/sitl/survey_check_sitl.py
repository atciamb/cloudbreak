"""SITL check that a fence-aware SURVEY (missions.survey_items_fenced) flies inside the site's geofence.

    # SITL homed in the site with Tutor-like speed (see fit_check_sitl.py), signing key installed, then:
    .venv\\Scripts\\python sim\\sitl\\survey_check_sitl.py --site schuyler [--nomination 2]

Mission: SITL takeoff -> start loiter over the survey centre -> (fence enabled once steady) survey lines -> end loiter.
Reports the minimum distance inside the fence along the flown track, breaches, and how much of the nominated strip
area the camera swath covered (narrow camera axis across track: conservative).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shapely.geometry import LineString, Point, Polygon  # noqa: E402

from cloudbreak.common.config import data_dir, set_site, site  # noqa: E402
from cloudbreak.common.fence import check_path, site_fence  # noqa: E402
from cloudbreak.common.geodesy import enu_offset, lonlat_to_utm  # noqa: E402
from cloudbreak.common.mav import CORE_SYSID, GOVERNOR_SYSID, Link, MissionItem, load_key, mavlink, mission_hash  # noqa: E402
from cloudbreak.common.missions import survey_items_fenced, survey_path_points, takeoff_items  # noqa: E402

EV: dict = {}


def record(name, ok, **info):
    EV[name] = dict(ok=bool(ok), **info)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {json.dumps(info, default=str)}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--nomination", type=int, default=2)
    ap.add_argument("--alt", type=float, default=45.0)
    ap.add_argument("--speedup", type=float, default=4.0)
    ap.add_argument("--wind-spd", type=float, default=1.2)
    ap.add_argument("--wind-dir", type=float, default=90.0)
    a = ap.parse_args(argv)
    set_site(a.site)
    import cloudbreak.ground.core.planner.strips as S
    from cloudbreak.ground.core.mapping.layers import load_layers

    cfg = S.load_aircraft()
    Lc = cfg["landing"]
    R = Lc["turn_radius_m"]
    fence = site_fence(site())
    layers = load_layers()
    noms = S.survey_nominations(layers, cfg, S.roughness_map(layers), Lc["hazard_buffer_m"])
    n = noms[a.nomination]
    lat0, lon0 = n["center_latlon"]
    Lreq = S.required_dims(cfg)[0]
    survey = survey_items_fenced(lat0, lon0, 84.0, Lreq + 40, n["axis_deg"], a.alt, 14.0, R, fence.polygon_latlon,
                                 fence.path_margin_m, 50.0)
    model = check_path(survey_path_points(survey, R), fence)
    print(f"nomination {a.nomination}: axis {n['axis_deg']} lines {len(survey) // 2}; modelled fence margin "
          f"{model.worst_margin_m:.1f} m ({model.reason})")
    wall = lambda s_: s_ / a.speedup                                          # noqa: E731
    key = load_key("sitl")
    gov = Link("tcp:127.0.0.1:5762", GOVERNOR_SYSID, key=key, role="rw", name="governor")
    core = Link("tcp:127.0.0.1:5763", CORE_SYSID, role="ro", name="core")
    pilot = Link("tcp:127.0.0.1:5765", GOVERNOR_SYSID, compid=191, key=key, role="ro", name="sim_pilot")
    for l in (gov, core, pilot):
        l.wait_heartbeat(60)

    def setp(name, val):
        t = time.perf_counter()
        gov.send("param_set_send", gov.ts, 1, name.encode(), float(val), mavlink.MAV_PARAM_TYPE_REAL32)
        gov.wait("PARAM_VALUE", lambda m: m.param_id == name, timeout=3, since=t)

    for k, v in dict(SIM_SPEEDUP=a.speedup, SIM_WIND_SPD=a.wind_spd, SIM_WIND_DIR=a.wind_dir, SIM_WIND_TURB=0.5,
                     FENCE_ENABLE=0, FENCE_TYPE=5, FENCE_ACTION=1, FENCE_ALT_MAX=fence.alt_max_m, FENCE_OPTIONS=0,
                     FENCE_RET_ALT=50, RTL_ALTITUDE=50).items():
        setp(k, v)
    hold = lambda label: MissionItem(mavlink.MAV_CMD_NAV_LOITER_UNLIM, param3=Lc["hold_radius_m"], lat=lat0, lon=lon0,  # noqa: E731
                                     alt=a.alt, label=label)
    items = takeoff_items(30.0) + [hold("start")] + survey + [hold("end")]
    seq_start, seq_first, seq_end = 2, 3, len(items)
    gov.upload_mission(items)
    record("upload_readback", mission_hash(gov.download_mission()) == mission_hash(items), n=len(items))
    gov.upload_fence_polygon(fence.polygon_latlon)
    time.sleep(2)
    cur = lambda: getattr(core.get("MISSION_CURRENT"), "seq", None)          # noqa: E731

    def wait(pred, sim_timeout):
        end = time.monotonic() + wall(sim_timeout)
        while time.monotonic() < end:
            if pred():
                return True
            time.sleep(0.1)
        return False

    wait(lambda: core.get("GPS_RAW_INT") and core.get("GPS_RAW_INT").fix_type >= 3 and core.get("EKF_STATUS_REPORT")
         and core.get("EKF_STATUS_REPORT").flags & 0x10, 180)
    gov.set_mode("FBWA")
    arm = None
    for _ in range(20):
        arm = pilot.command_long(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1, timeout=2)
        if arm == 0:
            break
        time.sleep(wall(3))
    record("arm", arm == 0, result=arm)
    if arm != 0:
        return 1
    gov.set_mode("AUTO")

    def steady(sim_s=25.0):
        end, since = time.monotonic() + wall(600), None
        while time.monotonic() < end:
            g = core.get("GLOBAL_POSITION_INT")
            ok = False
            if g is not None and cur() == seq_start:
                de, dn = enu_offset(lat0, lon0, g.lat / 1e7, g.lon / 1e7)
                ok = abs(math.hypot(de, dn) - R) < 25 and g.relative_alt / 1000 > a.alt - 6
            since = (since or time.monotonic()) if ok else None
            if since and time.monotonic() - since >= wall(sim_s):
                return True
            time.sleep(0.1)
        return False

    record("steady_in_start_loiter", steady())
    setp("FENCE_ENABLE", 1)
    track, modes, stop = [], [], threading.Event()

    def recorder():
        last = None
        while not stop.is_set():
            g = core.get("GLOBAL_POSITION_INT")
            att = core.get("ATTITUDE")
            if g is not None:
                track.append((g.lat / 1e7, g.lon / 1e7, g.relative_alt / 1000, cur(), abs(math.degrees(att.roll)) if att else 99))
            m = core.flightmode()
            if m != last:
                modes.append(m)
                last = m
            time.sleep(0.1)

    threading.Thread(target=recorder, daemon=True).start()
    gov.set_current(seq_first)
    done = wait(lambda: cur() == seq_end, 1500)
    time.sleep(wall(10))
    stop.set()
    record("survey_completed", done, seq=cur())
    fs = core.get("FENCE_STATUS")
    record("no_fence_breach", (fs is None or fs.breach_count == 0) and "RTL" not in modes,
           breach_count=None if fs is None else fs.breach_count, modes=modes)
    poly = fence.utm_polygon()
    flown = [(la, lo) for la, lo, al, sq, r in track if al > 5]
    m = [poly.exterior.distance(Point(*lonlat_to_utm(lo, la))) * (1 if poly.contains(Point(*lonlat_to_utm(lo, la))) else -1)
         for la, lo in flown]
    record("flown_track_inside_fence", bool(m) and min(m) >= 0, min_margin_m=round(min(m), 1) if m else None,
           modelled_margin_m=round(model.worst_margin_m, 1))
    # coverage of the nominated strip area by the camera swath (narrow axis across track, wings within 15 deg of level)
    half_swath = a.alt * math.tan(math.radians(41.0 / 2))
    area = Polygon([lonlat_to_utm(lo, la) for la, lo in n["corners_latlon"]]).buffer(0)
    level = [lonlat_to_utm(lo, la) for la, lo, al, sq, r in track if sq is not None and seq_first <= sq < seq_end and r < 15]
    cov = 0.0
    if len(level) > 2:
        cov = LineString(level).buffer(half_swath).intersection(area).area / area.area
    record("strip_area_covered", cov >= 0.9, coverage=round(cov, 3), half_swath_m=round(half_swath, 1))
    out = data_dir() / "sitl_verify"
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"surveycheck_{a.site}_{time.strftime('%Y%m%dT%H%M%S')}.json"
    p.write_text(json.dumps(dict(site=a.site, nomination=n, events=EV, track=track, modes=modes), indent=1, default=str))
    allok = all(v["ok"] for v in EV.values())
    print(f"\n{'ALL PASS' if allok else 'SOME CHECKS FAILED'} -> {p}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
