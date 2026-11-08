"""Bench motor run through the REAL FC (prop OFF): temporary arming at the bench, then restore and re-audit.

    .venv\\Scripts\\python scripts\\bench_motor_run.py              # interactive; goes through the signing proxy
    .venv\\Scripts\\python scripts\\bench_motor_run.py --restore    # put back the values from the last restore file

The FC refuses to arm at the bench (Schuyler fence, no GPS fix, uncalibrated compass, EKF heading), which is
correct. This procedure (STATUS.md section 2 #6, approved by P1) relaxes exactly that for one short run:
  1. saves the original values to C:\\cb-data\\fc\\motor_bench_restore_<time>.json BEFORE changing anything
  2. temporarily: FENCE_ENABLE 0, ARMING_SKIPCHK = compass + GPS lock + INS/AHRS + GPS config, THR_MAX 40 %
  3. arms only with the throttle stick down, mode FBWA/MANUAL, RC healthy and the pack above 11 V
  4. while armed, disarms at once if the mode changes (a failsafe CIRCLE/RTL would drive the throttle by itself),
     RC goes unhealthy, the FC heartbeat goes stale, Ctrl+C, or --max-seconds passes
  5. always (finally): disarm, restore ARMING_SKIPCHK + THR_MAX, then FENCE_ENABLE last; then re-audit:
     config/fc_params.toml (all sections, + fence) vs the FC, targets.toml [real.param_audit], ARMING_SKIPCHK 0 and
     the Schuyler fence polygon. It reports PASS only if every one matches.
Prop OFF, motor secured, hands and wires clear of the bell. Every power event per P1.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudbreak.common.config import data_dir, load_toml, set_site, site  # noqa: E402
from cloudbreak.common.fence import site_fence  # noqa: E402
from cloudbreak.common.mav import Link, mavlink  # noqa: E402

FC_SYSID = 42
PROXY = "tcp:127.0.0.1:5770"
# ARMING_SKIPCHK bits (ArduPilot 4.7): 2 compass, 3 GPS lock, 4 INS (incl. AHRS/EKF), 12 GPS configuration
SKIP_BITS = (1 << 2) | (1 << 3) | (1 << 4) | (1 << 12)
TEMP = {"ARMING_SKIPCHK": float(SKIP_BITS), "THR_MAX": 40.0, "FENCE_ENABLE": 0.0}
RESTORE_ORDER = ["ARMING_SKIPCHK", "THR_MAX", "FENCE_ENABLE"]     # fence goes back on last
OK_MODES = {"FBWA", "MANUAL"}
FORCE_DISARM = 21196


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fc_heartbeat(link: Link, max_age: float = 2.0):
    now = time.perf_counter()
    for t, m in reversed(list(link._inbox)):
        if now - t > max_age:
            return None
        if m.get_type() == "HEARTBEAT" and m.get_srcSystem() == FC_SYSID and m.get_srcComponent() == 1:
            return m
    return None


def armed(link: Link) -> bool | None:
    hb = fc_heartbeat(link)
    return None if hb is None else bool(hb.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)


def get(link: Link, name: str):
    for _ in range(4):
        v = link.get_param(name, timeout=2)
        if v is not None:
            return v
    return None


def set_param(link: Link, name: str, value: float) -> bool:
    for _ in range(3):
        t = time.perf_counter()
        link.send("param_set_send", FC_SYSID, 1, name.encode(), float(value), mavlink.MAV_PARAM_TYPE_REAL32)
        link.wait("PARAM_VALUE", lambda m: m.param_id == name, timeout=3, since=t)
        back = get(link, name)
        if back is not None and abs(back - value) < 1e-3:
            log(f"  {name} = {value:g} (read back {back:g})")
            return True
    log(f"  {name} = {value:g}: NOT CONFIRMED")
    return False


def disarm(link: Link) -> bool:
    for force in (0, FORCE_DISARM, FORCE_DISARM):
        link.command_long(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, force, timeout=2, retries=1)
        time.sleep(0.6)
        if armed(link) is False:
            log("DISARMED" + (" (forced)" if force else ""))
            return True
    log("!!! could not confirm DISARM: unplug the battery now")
    return False


def restore(link: Link, original: dict) -> bool:
    ok = True
    for k in RESTORE_ORDER:
        if k in original and original[k] is not None:
            ok &= set_param(link, k, original[k])
    return ok


def audit(link: Link) -> dict:
    cfg = load_toml("fc_params.toml")
    plan = {**cfg["params"], **cfg.get("outputs", {}), **cfg.get("radio", {}), **cfg["fence"]}
    set_site("schuyler")
    fence = site_fence(site())
    plan["FENCE_ALT_MAX"] = fence.alt_max_m
    plan["ARMING_SKIPCHK"] = 0
    for k, (want, tol) in load_toml("targets.toml")["real"]["param_audit"].items():
        plan.setdefault(k, want)
    bad = {}
    for k, want in plan.items():
        v = get(link, k)
        if v is None or abs(v - float(want)) > 1e-3:
            bad[k] = (v, want)
    have = [(round(it.lat * 1e7), round(it.lon * 1e7)) for it in
            link.download_mission(mission_type=mavlink.MAV_MISSION_TYPE_FENCE)]
    want_pts = [(round(lat * 1e7), round(lon * 1e7)) for lat, lon in fence.polygon_latlon]
    poly_ok = have == want_pts
    return dict(checked=len(plan), mismatches=bad, fence_vertices=len(have), fence_polygon_same=poly_ok,
                passed=not bad and poly_ok)


def preflight(link: Link, a) -> str | None:
    """None if it's OK to arm, else the reason."""
    rc, ss, bat = link.get("RC_CHANNELS"), link.get("SYS_STATUS"), link.get("BATTERY_STATUS")
    rc3_min = get(link, "RC3_MIN") or 1000
    if rc is None or not rc.chancount:
        return "no RC"
    if not ss.onboard_control_sensors_health & mavlink.MAV_SYS_STATUS_SENSOR_RC_RECEIVER:
        return "RC unhealthy"
    if rc.chan3_raw > rc3_min + 40:
        return f"throttle stick not down (ch3 {rc.chan3_raw}, min {rc3_min:g})"
    if link.flightmode() not in OK_MODES:
        return f"mode {link.flightmode()} (needs FBWA or MANUAL: put the mode switch LOW)"
    v = bat.voltages[0] / 1000 if bat else 0
    if v < 11.0:
        return f"pack {v:.2f} V (needs > 11 V)"
    return None


def run(link: Link, a) -> dict:
    res: dict = dict(start=time.strftime("%Y-%m-%dT%H:%M:%S"))
    if armed(link):
        raise SystemExit("refusing: the FC is already armed")
    original = {k: get(link, k) for k in TEMP}
    if any(v is None for v in original.values()):
        raise SystemExit(f"could not read originals: {original}")
    rpath = data_dir() / "fc" / f"motor_bench_restore_{time.strftime('%Y%m%dT%H%M%S')}.json"
    rpath.write_text(json.dumps(original, indent=1))
    res["original"], res["restore_file"] = original, str(rpath)
    log(f"originals saved to {rpath}: {original}")
    if not a.yes:
        print("\nProp OFF? Motor secured? Hands and wires clear of the motor? Iain (P1) approved?")
        if input("Type YES to continue: ").strip().lower() != "yes":
            raise SystemExit("not confirmed; nothing changed")
    armed_at = None
    trace = []
    try:
        log("temporary bench settings:")
        for k in ("ARMING_SKIPCHK", "THR_MAX", "FENCE_ENABLE"):
            if not set_param(link, k, TEMP[k]):
                raise RuntimeError(f"could not set {k}")
        time.sleep(1.5)
        t0 = time.perf_counter()
        link.command_long(mavlink.MAV_CMD_RUN_PREARM_CHECKS, timeout=2)
        time.sleep(3)
        left = sorted({m.text for t, m in list(link._inbox) if t >= t0 and m.get_type() == "STATUSTEXT"
                       and m.text.startswith("PreArm")})
        res["prearm_left"] = left
        if left:
            log("pre-arm still reports: " + " | ".join(left))
        why = preflight(link, a)
        while why is not None:
            log(f"not arming yet: {why}. Fix it (30 s) ...")
            deadline = time.time() + 30
            while time.time() < deadline and (why := preflight(link, a)) is not None:
                time.sleep(0.5)
            if why is not None:
                raise RuntimeError(f"preflight not met: {why}")
        log("ARMING (throttle stick down, mode %s)" % link.flightmode())
        t1 = time.perf_counter()
        r = link.command_long(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1, 0, timeout=3, retries=1)
        time.sleep(1.0)
        if not armed(link):
            texts = [m.text for t, m in list(link._inbox) if t >= t1 and m.get_type() == "STATUSTEXT"]
            res["arm_refused"] = dict(result=r, text=texts)
            raise RuntimeError(f"FC refused to arm (result {r}): {' | '.join(texts[-4:])}")
        armed_at = time.time()
        res["armed_at"] = time.strftime("%H:%M:%S")
        log(f"ARMED. Raise the throttle stick SLOWLY (capped at {TEMP['THR_MAX']:g} %). Watch which way the motor "
            f"turns. Throttle down + Ctrl+C (or wait {a.max_seconds:g} s) to finish.")
        last_print = 0
        while True:
            time.sleep(0.1)
            hb = fc_heartbeat(link, max_age=1.5)
            rc, ss, so = link.get("RC_CHANNELS"), link.get("SYS_STATUS"), link.get("SERVO_OUTPUT_RAW")
            mode = link.flightmode()
            if hb is None:
                raise RuntimeError("FC heartbeat stale")
            if not hb.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
                log("FC disarmed itself")
                break
            if mode not in OK_MODES:
                raise RuntimeError(f"mode changed to {mode}")
            if not ss.onboard_control_sensors_health & mavlink.MAV_SYS_STATUS_SENSOR_RC_RECEIVER:
                raise RuntimeError("RC unhealthy")
            if time.time() - armed_at > a.max_seconds:
                log(f"{a.max_seconds:g} s up")
                break
            if time.time() - last_print > 0.5 and so is not None:
                last_print = time.time()
                s1 = so.servo1_raw
                trace.append((round(time.time() - armed_at, 1), rc.chan3_raw, s1))
                print(f"\r  throttle stick {rc.chan3_raw}  ->  S1 (ESC) {s1} us   ", end="", flush=True)
    except KeyboardInterrupt:
        print()
        log("Ctrl+C")
    except Exception as e:
        print()
        log(f"STOP: {e}")
        res["stopped_because"] = str(e)
    finally:
        if armed(link) is not False:
            res["disarmed"] = disarm(link)
        else:
            res["disarmed"] = True
        res["armed_seconds"] = None if armed_at is None else round(time.time() - armed_at, 1)
        res["throttle_trace"] = trace
        res["max_s1_us"] = max((s for _, _, s in trace), default=None)
        log("restoring:")
        res["restored"] = restore(link, original)
        log("re-audit:")
        au = audit(link)
        res["audit"] = au
        log(f"  {au['checked']} values checked, mismatches {au['mismatches'] or 'none'}; fence polygon "
            f"{au['fence_vertices']} vertices, same as config: {au['fence_polygon_same']}")
        log("PASS: FC back to its flight configuration" if au["passed"] and res["restored"] and res["disarmed"]
            else "!!! NOT RESTORED: run  scripts\\bench_motor_run.py --restore  and check before anything else")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", default=PROXY)
    ap.add_argument("--max-seconds", type=float, default=90.0)
    ap.add_argument("--restore", action="store_true", help="re-apply the newest restore file, then re-audit")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    link = Link(a.port, 255, compid=190, role="ro", name="motor-bench")
    link.wait_heartbeat(15)
    if link.ts != FC_SYSID or link.get_param("SIM_SPEEDUP", timeout=1.5) is not None:
        raise SystemExit("refusing: not the real FC")
    link.send("request_data_stream_send", FC_SYSID, 1, mavlink.MAV_DATA_STREAM_ALL, 5, 1)
    link.send("request_data_stream_send", FC_SYSID, 1, mavlink.MAV_DATA_STREAM_RC_CHANNELS, 10, 1)
    time.sleep(1.5)
    if a.restore:
        files = sorted((data_dir() / "fc").glob("motor_bench_restore_*.json"))
        if not files:
            raise SystemExit("no restore file")
        original = json.loads(files[-1].read_text())
        if armed(link):
            disarm(link)
        ok = restore(link, original)
        au = audit(link)
        print(json.dumps(dict(restored=ok, audit=au), indent=1))
        return 0 if ok and au["passed"] else 1
    res = run(link, a)
    p = data_dir() / "fc" / f"bench_motor_{time.strftime('%Y%m%dT%H%M%S')}.json"
    p.write_text(json.dumps(res, indent=1, default=str))
    print(f"record: {p}")
    return 0 if res.get("audit", {}).get("passed") and res.get("restored") else 1


if __name__ == "__main__":
    sys.exit(main())
