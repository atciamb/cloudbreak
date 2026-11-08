"""Bench checks and calibrations for the REAL flight controller from this laptop, without Mission Planner.

Runs through the signing proxy (scripts/gcs_proxy.py, default tcp:127.0.0.1:5770) or straight on the FC's USB port
(--port COM5; the FC accepts unsigned commands on USB, and reading needs no key). Prop OFF, power per P1.

    .venv\\Scripts\\python scripts\\fc_bench.py status        # health, pre-arm failures, GPS/compass/RC/SD card, outputs
    .venv\\Scripts\\python scripts\\fc_bench.py outputs       # output map read-back printout (for P1 before the ESC goes on S1)
    .venv\\Scripts\\python scripts\\fc_bench.py rc [--seconds 30]          # live RC channels: bind check, switch check
    .venv\\Scripts\\python scripts\\fc_bench.py logs          # DataFlash logs on the microSD card (proves the card works)
    .venv\\Scripts\\python scripts\\fc_bench.py accel         # 6-position accelerometer calibration (detects each position)
    .venv\\Scripts\\python scripts\\fc_bench.py level         # "Calibrate Level": plane installed, held at flying attitude
    .venv\\Scripts\\python scripts\\fc_bench.py compass [--accept]        # onboard compass calibration (outdoors, installed)
    .venv\\Scripts\\python scripts\\fc_bench.py radio [--yes] # radio calibration: RCn_MIN/MAX/TRIM from stick sweeps
    .venv\\Scripts\\python scripts\\fc_bench.py servos        # live sticks -> surface outputs (+ FC tilt) for direction checks
    .venv\\Scripts\\python scripts\\fc_bench.py mode MANUAL   # set the flight mode from the laptop (disarmed only)
    .venv\\Scripts\\python scripts\\fc_bench.py reverse 6     # flip SERVO6_REVERSED (surface outputs S3-S6, disarmed only)

Every run writes a JSON record to C:\\cb-data\\fc\\bench_<command>_<time>.json (evidence for docs/CHECKLIST.md).
"""
from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudbreak.common.config import data_dir  # noqa: E402
from cloudbreak.common.mav import Link, LinkError, mavlink  # noqa: E402

BENCH_SYSID, BENCH_COMPID = 255, 190          # an ordinary GCS identity (not the governor's 245)
FC_SYSID = 42
PROXY = "tcp:127.0.0.1:5770"

FUNCTION_NAMES = {0: "disabled", 4: "aileron", 19: "elevator", 21: "rudder", 70: "throttle (ESC)", 77: "elevon left",
                  78: "elevon right", 79: "vtail left", 80: "vtail right", 1: "RC passthrough", 33: "motor 1"}
WANT_OUTPUTS = {1: 70, 2: 0, 3: 4, 4: 4, 5: 19, 6: 21}

# accel cal positions (ACCELCAL_VEHICLE_POS) and the specific force the accelerometer reads in each (FRD body, g)
POSITIONS = {1: ("LEVEL", "flat, top up", (0, 0, -1)),
             2: ("LEFT", "on its LEFT side (left edge down)", (0, 1, 0)),
             3: ("RIGHT", "on its RIGHT side (right edge down)", (0, -1, 0)),
             4: ("NOSE DOWN", "nose straight DOWN (arrow pointing at the floor)", (-1, 0, 0)),
             5: ("NOSE UP", "nose straight UP (arrow pointing at the ceiling)", (1, 0, 0)),
             6: ("BACK", "upside down (top facing the desk)", (0, 0, 1))}
ACCELCAL_SUCCESS, ACCELCAL_FAILED = 16777215, 16777216


def record(kind: str, data: dict) -> Path:
    d = data_dir() / "fc"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"bench_{kind}_{time.strftime('%Y%m%dT%H%M%S')}.json"
    p.write_text(json.dumps(data, indent=2, default=str))
    return p


def default_port() -> str:
    try:
        socket.create_connection(("127.0.0.1", 5770), timeout=1).close()
        return PROXY
    except OSError:
        pass
    from cloudbreak.ground.gcs_proxy import find_fc_port

    p = find_fc_port()
    if p is None:
        raise SystemExit("No proxy on 127.0.0.1:5770 and no ArduPilot USB port. Start scripts/gcs_proxy.py or pass --port.")
    return p


def connect(port: str) -> Link:
    link = Link(port, BENCH_SYSID, compid=BENCH_COMPID, role="ro", name="fc-bench")
    link.wait_heartbeat(15)
    if link.ts != FC_SYSID:
        raise SystemExit(f"refusing: heartbeat from sysid {link.ts}, expected the real FC ({FC_SYSID})")
    if link.get_param("SIM_SPEEDUP", timeout=1.5) is not None:
        raise SystemExit("refusing: this is SITL, not the real FC")
    return link


def params(link: Link, names) -> dict:
    out = {}
    for n in names:
        v = None
        for _ in range(3):
            v = link.get_param(n, timeout=2)
            if v is not None:
                break
        out[n] = v
    return out


def statustexts(link: Link, since: float) -> list[str]:
    return [m.text for t, m in list(link._inbox) if t >= since and m.get_type() == "STATUSTEXT"]


def decode_dev_id(dev_id: float | None) -> str:
    if not dev_id:
        return "none"
    d = int(dev_id)
    bus_type, bus, addr, devtype = d & 7, (d >> 3) & 31, (d >> 8) & 255, (d >> 16) & 255
    kinds = {1: "I2C", 2: "SPI", 3: "UAVCAN", 4: "SITL", 5: "MSP", 6: "serial"}
    names = {0x0D: "QMC5883L", 0x11: "IST8310", 0x05: "HMC5883", 0x0B: "LIS3MDL", 0x13: "RM3100", 0x0E: "BMM150",
             0x14: "MMC3416", 0x15: "MMC5983"}
    return f"{names.get(devtype, f'type 0x{devtype:02x}')} on {kinds.get(bus_type, bus_type)} bus {bus} addr 0x{addr:02x}"


def sensor_health(ss) -> dict:
    out = {}
    for v, e in mavlink.enums["MAV_SYS_STATUS_SENSOR"].items():
        if not isinstance(v, int) or v <= 0 or v & (v - 1) or not (ss.onboard_control_sensors_present & v):
            continue
        out[e.name.replace("MAV_SYS_STATUS_", "")] = dict(enabled=bool(ss.onboard_control_sensors_enabled & v),
                                                          healthy=bool(ss.onboard_control_sensors_health & v))
    return out


# ----------------------------------------------------------------------------- read-only commands
def cmd_outputs(link: Link, a) -> dict:
    names = [f"SERVO{n}_{k}" for n in range(1, 9) for k in ("FUNCTION", "MIN", "TRIM", "MAX", "REVERSED")]
    p = params(link, names)
    link.command_long(mavlink.MAV_CMD_REQUEST_MESSAGE, mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW, timeout=2)
    raw = link.wait("SERVO_OUTPUT_RAW", timeout=3)
    print(f"Output map read back from the FC at {time.strftime('%H:%M:%S')} (disarmed outputs in us):")
    print("  out  function             want   min  trim   max  rev  now")
    rows, ok, warnings = [], True, []
    armed = bool(link.get("HEARTBEAT").base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
    for n in range(1, 9):
        f = p[f"SERVO{n}_FUNCTION"]
        want = WANT_OUTPUTS.get(n)
        now = getattr(raw, f"servo{n}_raw", None) if raw is not None else None
        good = want is None or (f is not None and int(f) == want)
        ok &= good
        fn = "?" if f is None else f"{int(f)} {FUNCTION_NAMES.get(int(f), '')}"
        note = "" if good else "   <-- WRONG"
        trim, lo = p[f"SERVO{n}_TRIM"], p[f"SERVO{n}_MIN"]
        if f is not None and int(f) in (4, 19, 21) and trim is not None and not 1400 <= trim <= 1600:
            warnings.append(f"S{n} {FUNCTION_NAMES[int(f)]}: SERVO{n}_TRIM {trim:g} is far from centre (surface sits deflected)")
            note += "   <-- trim"
        if f is not None and int(f) == 70 and not armed and now and lo and now > lo + 50:
            warnings.append(f"S{n} throttle outputs {now} us while DISARMED (min {lo:g}): reboot the FC, re-check, and "
                            f"keep the ESC unplugged until it reads the minimum")
            note += "   <-- throttle not at min"
        print(f"  S{n}   {fn:20s} {'' if want is None else want:>4}  {lo!s:>5} {trim!s:>5}"
              f" {p[f'SERVO{n}_MAX']!s:>5}  {p[f'SERVO{n}_REVERSED']!s:>3}  {now}{note}")
        rows.append(dict(out=n, function=f, want=want, now=now, **{k: p[f"SERVO{n}_{k}"] for k in ("MIN", "TRIM", "MAX", "REVERSED")}))
    for w in warnings:
        print("WARNING: " + w)
    if not ok:
        print("MAP DOES NOT MATCH: do not plug the ESC into S1")
    elif warnings:
        print("map matches STATUS.md section 2 #1, but fix the warnings before the ESC goes on S1")
    else:
        print("map matches STATUS.md section 2 #1; throttle at minimum while disarmed; surface trims centred")
    return dict(ok=ok and not warnings, map_ok=ok, warnings=warnings, outputs=rows)


def cmd_status(link: Link, a) -> dict:
    t0 = time.perf_counter()
    link.command_long(mavlink.MAV_CMD_RUN_PREARM_CHECKS, timeout=2)
    for mid in (mavlink.MAVLINK_MSG_ID_SYS_STATUS, mavlink.MAVLINK_MSG_ID_GPS_RAW_INT, mavlink.MAVLINK_MSG_ID_RC_CHANNELS,
                mavlink.MAVLINK_MSG_ID_BATTERY_STATUS):
        link.command_long(mavlink.MAV_CMD_REQUEST_MESSAGE, mid, timeout=1, retries=0)
    time.sleep(2.5)
    hb = link.get("HEARTBEAT")
    ss, gps, rc, bat = (link.get(t) for t in ("SYS_STATUS", "GPS_RAW_INT", "RC_CHANNELS", "BATTERY_STATUS"))
    p = params(link, ["COMPASS_DEV_ID", "COMPASS_DEV_ID2", "COMPASS_USE", "COMPASS_EXTERNAL", "COMPASS_ORIENT",
                      "COMPASS_OFS_X", "COMPASS_OFS_Y", "COMPASS_OFS_Z", "INS_ACCOFFS_X", "INS_ACCOFFS_Y", "INS_ACCOFFS_Z",
                      "INS_ACCSCAL_X", "INS_ACCSCAL_Y", "INS_ACCSCAL_Z", "AHRS_TRIM_X", "AHRS_TRIM_Y", "GPS1_TYPE",
                      "SERIAL5_PROTOCOL", "SERIAL6_PROTOCOL", "RC_PROTOCOLS", "FENCE_ENABLE", "LOG_BACKEND_TYPE",
                      "BATT_MONITOR", "RC1_MIN", "RC1_MAX", "RC3_MIN", "RC3_MAX", "FLTMODE_CH"])
    texts = statustexts(link, t0)
    armed = bool(hb.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
    accel_cal = any(abs((p[f"INS_ACCOFFS_{ax}"] or 0)) > 1e-6 for ax in "XYZ") or any(
        abs((p[f"INS_ACCSCAL_{ax}"] or 1) - 1) > 1e-6 for ax in "XYZ")
    comp_cal = any(abs(p[f"COMPASS_OFS_{ax}"] or 0) > 1e-6 for ax in "XYZ")
    fix_names = {0: "no GPS detected", 1: "GPS detected, no fix", 2: "2D fix", 3: "3D fix", 4: "DGPS", 5: "RTK float",
                 6: "RTK fixed"}
    health = sensor_health(ss) if ss else {}
    res = dict(
        mode=link.flightmode(), armed=armed,
        prearm=[t for t in texts if t.startswith("PreArm")],
        other_text=[t for t in texts if not t.startswith("PreArm")],
        gps=None if gps is None else dict(fix=fix_names.get(gps.fix_type, gps.fix_type), sats=gps.satellites_visible,
                                          detected=gps.fix_type >= 1),
        compass=dict(primary=decode_dev_id(p["COMPASS_DEV_ID"]), second=decode_dev_id(p["COMPASS_DEV_ID2"]),
                     external=p["COMPASS_EXTERNAL"], orient=p["COMPASS_ORIENT"], calibrated=comp_cal),
        accel_calibrated=accel_cal, level_trim=(p["AHRS_TRIM_X"], p["AHRS_TRIM_Y"]),
        rc=None if rc is None else dict(channels=rc.chancount, rssi=rc.rssi,
                                        values=[getattr(rc, f"chan{i}_raw") for i in range(1, 9)]),
        rc_port=dict(SERIAL6_PROTOCOL=p["SERIAL6_PROTOCOL"], RC_PROTOCOLS=p["RC_PROTOCOLS"]),
        battery_v=None if bat is None else round(bat.voltages[0] / 1000, 2),
        unhealthy=[k for k, v in health.items() if v["enabled"] and not v["healthy"]],
        logging=health.get("LOGGING"),
        fence_enable=p["FENCE_ENABLE"],
    )
    print(f"FC sysid {link.ts}: mode {res['mode']}, {'ARMED' if armed else 'disarmed'}, battery {res['battery_v']} V")
    print(f"  GPS:      {res['gps']}")
    print(f"  compass:  {res['compass']['primary']}; calibrated: {comp_cal}")
    print(f"  accel:    calibrated: {accel_cal}; level trim (rad) {res['level_trim']}")
    print(f"  RC:       {res['rc']}  (SERIAL6_PROTOCOL {p['SERIAL6_PROTOCOL']:g} = RCIN)" if res["rc"] else "  RC: no RC_CHANNELS")
    print(f"  logging:  {res['logging']}")
    print(f"  unhealthy sensors: {res['unhealthy'] or 'none'}")
    print("  pre-arm failures:" + ("" if res["prearm"] else " none reported"))
    for t in res["prearm"]:
        print("    " + t)
    res["outputs"] = cmd_outputs(link, a)
    return res


def cmd_rc(link: Link, a) -> dict:
    link.send("request_data_stream_send", link.ts, 1, mavlink.MAV_DATA_STREAM_RC_CHANNELS, 10, 1)
    t0 = time.time()
    lo, hi, last, seen = [9999] * 16, [0] * 16, None, 0
    print(f"Reading RC for {a.seconds:g} s: move every stick and switch. Ctrl+C to stop.")
    try:
        while time.time() - t0 < a.seconds:
            m = link.wait("RC_CHANNELS", timeout=1.0, since=time.perf_counter() - 0.05)
            if m is None:
                continue
            last = m
            vals = [getattr(m, f"chan{i}_raw") for i in range(1, 17)]
            if m.chancount:
                seen += 1
                for i, v in enumerate(vals[:m.chancount]):
                    lo[i], hi[i] = min(lo[i], v), max(hi[i], v)
            print("\r  ch " + " ".join(f"{i + 1}:{v:4d}" for i, v in enumerate(vals[:8])) +
                  f"  count {m.chancount} rssi {m.rssi}   ", end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    print()
    n = last.chancount if last else 0
    if not seen:
        print("No RC input: the FC reports 0 channels. Check that the XR1 is bound to the Pocket (bind is P4's job),\n"
              "the transmitter is on, and the XR1 wiring: XR1 TX -> R6, RX -> T6, 5V -> 4V5, GND (SERIAL6 = RCIN).")
        return dict(ok=False, channels=0)
    ranges = {i + 1: (lo[i], hi[i]) for i in range(n)}
    for ch, (l, h) in ranges.items():
        print(f"  ch{ch}: {l}..{h}")
    return dict(ok=True, channels=n, ranges=ranges)


def cmd_logs(link: Link, a) -> dict:
    t = time.perf_counter()
    link.send("log_request_list_send", link.ts, 1, 0, 0xFFFF)
    entries = {}
    deadline = time.time() + 6
    while time.time() < deadline:
        m = link.wait("LOG_ENTRY", lambda m: m.id not in entries, timeout=1.5, since=t)
        if m is None:
            break
        entries[m.id] = m
        if m.num_logs and len(entries) >= m.num_logs:
            break
    n = next(iter(entries.values())).num_logs if entries else 0
    # card presence: ArduPilot's pre-arm reports EVERY failing check, including "No SD card" / "Logging failed"
    t1 = time.perf_counter()
    link.command_long(mavlink.MAV_CMD_RUN_PREARM_CHECKS, timeout=2)
    link.command_long(mavlink.MAV_CMD_REQUEST_MESSAGE, mavlink.MAVLINK_MSG_ID_SYS_STATUS, timeout=1, retries=0)
    time.sleep(2.5)
    prearm = [t for t in statustexts(link, t1) if t.startswith("PreArm")]
    card_msgs = [t for t in prearm if any(w in t for w in ("SD", "Logging", "log"))]
    ss = link.get("SYS_STATUS")
    health = sensor_health(ss).get("LOGGING") if ss else None
    log_disarmed = link.get_param("LOG_DISARMED", timeout=2)
    card_ok = bool(prearm) and not card_msgs and bool(health and health["healthy"])
    print(f"logging health {health}; pre-arm card messages: {card_msgs or 'none'} "
          f"({len(prearm)} pre-arm line(s) seen); LOG_DISARMED {log_disarmed}")
    if card_ok:
        print("microSD card: present and healthy (no 'No SD card' / 'Logging failed' pre-arm, logging healthy)")
    elif not prearm:
        print("microSD card: unknown (no pre-arm report came back; run again)")
    else:
        print("microSD card: PROBLEM: " + "; ".join(card_msgs or ["logging unhealthy"]))
    if n == 0:
        print("0 logs on the card yet: ArduPilot writes a log while armed (LOG_DISARMED 0), so that is expected at the bench.")
    else:
        print(f"{n} log(s) on the card:")
    for i in sorted(entries):
        e = entries[i]
        if not e.size:
            continue
        when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(e.time_utc)) + " UTC" if e.time_utc else "no time (no GPS)"
        print(f"  log {e.id}: {e.size / 1024:.0f} kB, {when}")
    return dict(ok=card_ok, card_ok=card_ok, card_prearm=card_msgs, logging_health=health, num_logs=n,
                logs=[dict(id=e.id, size=e.size, time_utc=e.time_utc) for e in entries.values() if e.size])


# ----------------------------------------------------------------------------- calibrations
def _accel_vec(link: Link):
    m = link.get("RAW_IMU")
    if m is None:
        return None
    v = (m.xacc / 1000, m.yacc / 1000, m.zacc / 1000)
    n = math.sqrt(sum(c * c for c in v))
    return None if n < 0.5 else tuple(c / n for c in v)


def _wait_still_in(link: Link, want, hold_s: float = 1.5, cos_tol: float = math.cos(math.radians(20))):
    """Block until the accelerometer has pointed along `want` (within 20 deg) and stayed still for hold_s."""
    since, prev, t0, hinted = None, None, time.time(), 0
    while True:
        v = _accel_vec(link)
        if v is not None:
            dot = sum(x * y for x, y in zip(v, want))
            still = prev is not None and sum(x * y for x, y in zip(v, prev)) > math.cos(math.radians(2))
            if dot > cos_tol and still:
                since = since or time.time()
                if time.time() - since >= hold_s:
                    return v
            else:
                since = None
            prev = v
            if time.time() - t0 > 20 * (hinted + 1):
                hinted += 1
                off = math.degrees(math.acos(max(-1.0, min(1.0, dot))))
                print(f"      still waiting: the FC is {off:.0f} deg away from that position (accel "
                      f"{tuple(round(c, 2) for c in v)}, want {want}). Hold it square and still. "
                      f"(--manual skips the detection.)", flush=True)
        time.sleep(0.1)


def cmd_accel(link: Link, a) -> dict:
    if link.get("HEARTBEAT").base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
        raise SystemExit("refusing: FC is armed")
    link.send("request_data_stream_send", link.ts, 1, mavlink.MAV_DATA_STREAM_RAW_SENSORS, 10, 1)
    t0 = time.perf_counter()
    r = link.command_long(mavlink.MAV_CMD_PREFLIGHT_CALIBRATION, 0, 0, 0, 0, 1, 0, 0, timeout=4)
    if r != mavlink.MAV_RESULT_ACCEPTED:
        raise SystemExit(f"FC refused to start the accel calibration (result {r})")
    print("Accelerometer calibration started. Hold the FC square and still in each position; I detect it myself.")
    done, since, confirmed = [], t0, set()
    while True:
        # the FC repeats its request for the current position until it has taken the sample, so a request for a
        # position already confirmed is a repeat, not a new step
        req = link.wait("COMMAND_LONG", lambda m: m.command == mavlink.MAV_CMD_ACCELCAL_VEHICLE_POS
                        and int(m.param1) not in confirmed, timeout=60, since=since)
        if req is None:
            print("no request from the FC for 60 s: calibration aborted?")
            return dict(ok=False, done=done, text=statustexts(link, t0))
        since = time.perf_counter()
        pos = int(req.param1)
        if pos in (ACCELCAL_SUCCESS, ACCELCAL_FAILED):
            ok = pos == ACCELCAL_SUCCESS
            time.sleep(1)
            texts = statustexts(link, t0)
            print("CALIBRATION SUCCESSFUL" if ok else "CALIBRATION FAILED", "|", "; ".join(texts[-3:]))
            offs = params(link, [f"INS_ACC{k}_{ax}" for k in ("OFFS", "SCAL") for ax in "XYZ"])
            print("  " + ", ".join(f"{k} {v:.4f}" for k, v in offs.items() if v is not None))
            return dict(ok=ok, done=done, params=offs, text=texts)
        name, how, want = POSITIONS[pos]
        print(f"[{len(done) + 1}/6] Put the FC {how}." + (" Its LEFT is your left when you stand behind it, arrow "
              "pointing away from you." if pos in (2, 3) else ""), flush=True)
        if a.manual:
            input("      press Enter when it is in place and still ")
            v = _accel_vec(link)
        else:
            v = _wait_still_in(link, want)
        print(f"      {name} detected (accel {tuple(round(c, 2) for c in v)}): sampling, keep still...", flush=True)
        link.command_long(mavlink.MAV_CMD_ACCELCAL_VEHICLE_POS, pos, timeout=2, retries=1)
        confirmed.add(pos)
        done.append(name)


def cmd_level(link: Link, a) -> dict:
    t0 = time.perf_counter()
    print("Calibrate Level: the plane must sit at its normal flying attitude (wing level, nose at cruise angle) and be still.")
    if not a.yes:
        input("press Enter to start ")
    r = link.command_long(mavlink.MAV_CMD_PREFLIGHT_CALIBRATION, 0, 0, 0, 0, 2, 0, 0, timeout=8)
    time.sleep(2)
    trims = params(link, ["AHRS_TRIM_X", "AHRS_TRIM_Y"])
    print(f"result {r}; AHRS_TRIM_X {trims['AHRS_TRIM_X']} AHRS_TRIM_Y {trims['AHRS_TRIM_Y']} rad;",
          "; ".join(statustexts(link, t0)[-2:]))
    return dict(ok=r == mavlink.MAV_RESULT_ACCEPTED, trims=trims, text=statustexts(link, t0))


def cmd_compass(link: Link, a) -> dict:
    t0 = time.perf_counter()
    r = link.command_long(mavlink.MAV_CMD_DO_START_MAG_CAL, 0, 1, 0, 0, 0, timeout=3)
    if r != mavlink.MAV_RESULT_ACCEPTED:
        raise SystemExit(f"FC refused to start compass calibration (result {r})")
    print("Compass calibration running: rotate the whole plane slowly through every orientation (each face down,\n"
          "nose up/down, full turns) away from metal and cars. Ctrl+C cancels.")
    report = None
    try:
        while report is None:
            m = link.wait(["MAG_CAL_PROGRESS", "MAG_CAL_REPORT"], timeout=60, since=time.perf_counter() - 0.2)
            if m is None:
                print("\nno progress for 60 s")
                break
            if m.get_type() == "MAG_CAL_REPORT":
                report = m
            else:
                print(f"\r  compass {m.compass_id}: {m.completion_pct:3d} %   ", end="", flush=True)
    except KeyboardInterrupt:
        link.command_long(mavlink.MAV_CMD_DO_CANCEL_MAG_CAL, 0, timeout=2)
        print("\ncancelled")
        return dict(ok=False, cancelled=True)
    print()
    if report is None:
        return dict(ok=False)
    status = mavlink.enums["MAG_CAL_STATUS"][report.cal_status].name
    print(f"  {status}: fitness {report.fitness:.1f} mGauss (lower is better, < ~20 good), offsets "
          f"({report.ofs_x:.0f}, {report.ofs_y:.0f}, {report.ofs_z:.0f}), orientation {report.orientation_confidence:.2f} conf")
    ok = report.cal_status == mavlink.MAG_CAL_SUCCESS
    if ok and a.accept:
        link.command_long(mavlink.MAV_CMD_DO_ACCEPT_MAG_CAL, 0, timeout=3)
        print("  accepted and saved. Reboot the FC before flying.")
    elif ok:
        print("  not saved: re-run with --accept to keep a result like this")
    return dict(ok=ok, accepted=ok and a.accept, status=status, fitness=report.fitness,
                ofs=(report.ofs_x, report.ofs_y, report.ofs_z), text=statustexts(link, t0))


def cmd_radio(link: Link, a) -> dict:
    link.send("request_data_stream_send", link.ts, 1, mavlink.MAV_DATA_STREAM_RC_CHANNELS, 10, 1)
    m = link.wait("RC_CHANNELS", timeout=3)
    if m is None or not m.chancount:
        raise SystemExit("No RC input (0 channels). Bind the XR1 to the Pocket and switch the transmitter on first.")
    n = min(m.chancount, 8)
    lo, hi = [3000] * n, [0] * n
    full = lambda i: hi[i] - lo[i] >= 800          # a stick that went end to end (ELRS ~988..2012)
    done = threading.Event()
    if not a.yes:
        threading.Thread(target=lambda: (input(), done.set()), daemon=True).start()
    print(f"{m.chancount} channels. Move BOTH sticks end to end in every direction (full circles) and flip every\n"
          f"switch through all positions. 'ok' marks a channel whose full range has been seen. Press Enter when\n"
          f"ch1-ch4 all show ok (stops by itself after {a.seconds:g} s).")
    t0 = time.time()
    while time.time() - t0 < a.seconds and not done.is_set():
        r = link.wait("RC_CHANNELS", timeout=1, since=time.perf_counter() - 0.05)
        if r is None:
            continue
        for i in range(n):
            v = getattr(r, f"chan{i + 1}_raw")
            if 800 < v < 2200:
                lo[i], hi[i] = min(lo[i], v), max(hi[i], v)
        print("\r  " + " ".join(f"ch{i + 1} {lo[i]}-{hi[i]}{' ok' if full(i) else ''}" for i in range(n)) + "   ",
              end="", flush=True)
        time.sleep(0.1)
    print()
    short = [i + 1 for i in range(min(n, 4)) if not full(i)]
    if short:
        print(f"Sticks not swept end to end: ch{', ch'.join(map(str, short))}. Nothing written; run it again.")
        return dict(ok=False, ranges={i + 1: (lo[i], hi[i]) for i in range(n)}, written=False, short=short)
    if not a.yes:
        print("Now centre the sticks, throttle fully DOWN, switches at their normal positions; press Enter ",
              end="", flush=True)
        if done.is_set():
            input()
        else:
            done.wait()          # the sweep timed out: the Enter-reader thread is still waiting for this Enter
    else:
        print("centre the sticks, throttle DOWN: capturing trims in 5 s")
        time.sleep(5)
    r = link.wait("RC_CHANNELS", timeout=2, since=time.perf_counter())
    trims = [getattr(r, f"chan{i + 1}_raw") for i in range(n)]
    plan = {}
    for i in range(n):
        if hi[i] - lo[i] < 300:
            print(f"  ch{i + 1}: moved only {hi[i] - lo[i]} us: left unchanged")
            continue
        plan[f"RC{i + 1}_MIN"], plan[f"RC{i + 1}_MAX"] = lo[i], hi[i]
        plan[f"RC{i + 1}_TRIM"] = max(lo[i], min(hi[i], trims[i]))
    for k, v in plan.items():
        print(f"  {k} = {v}")
    if not a.yes:
        if input("write these to the FC? [y/N] ").strip().lower() != "y":
            return dict(ok=False, plan=plan, written=False)
    written = {}
    for k, v in plan.items():
        t = time.perf_counter()
        link.send("param_set_send", link.ts, 1, k.encode(), float(v), mavlink.MAV_PARAM_TYPE_REAL32)
        echo = link.wait("PARAM_VALUE", lambda m, k=k: m.param_id == k, timeout=3, since=t)
        written[k] = None if echo is None else echo.param_value
        print(f"  set {k} = {v}: {'ok' if echo is not None and abs(echo.param_value - v) < 0.5 else 'NOT CONFIRMED'}")
    return dict(ok=all(w is not None for w in written.values()), plan=plan, written=written)


SURFACES = {3: "ail S3", 4: "ail S4", 5: "elev S5", 6: "rud S6"}


def _disarmed(link: Link) -> bool:
    hb = link.get("HEARTBEAT")
    return hb is not None and not hb.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED


def cmd_servos(link: Link, a) -> dict:
    """Live stick -> surface view (read-only). One line each time a stick or a surface output moves."""
    link.send("request_data_stream_send", link.ts, 1, mavlink.MAV_DATA_STREAM_RC_CHANNELS, 10, 1)
    link.send("request_data_stream_send", link.ts, 1, mavlink.MAV_DATA_STREAM_EXTRA1, 10, 1)
    trims = {n: int(params(link, [f"SERVO{n}_TRIM"])[f"SERVO{n}_TRIM"] or 1500) for n in SURFACES}
    rev = {n: params(link, [f"SERVO{n}_REVERSED"])[f"SERVO{n}_REVERSED"] for n in SURFACES}
    print("Sticks: roll = RC1 (right = +), pitch = RC2 (forward/push = +), yaw = RC4 (right = +).\n"
          "Surfaces: output minus its trim, in us. Which way the surface physically moves is what you check.\n"
          f"Reversed now: {', '.join(f'S{n} {int(v or 0)}' for n, v in rev.items())}. Ctrl+C to stop.", flush=True)
    last, lines, t0 = None, [], time.time()
    try:
        while time.time() - t0 < a.seconds:
            time.sleep(0.1)
            rc, so, att = link.get("RC_CHANNELS"), link.get("SERVO_OUTPUT_RAW"), link.get("ATTITUDE")
            if rc is None or so is None:
                continue
            sticks = (rc.chan1_raw - 1500, rc.chan2_raw - 1500, rc.chan4_raw - 1500)
            outs = {n: getattr(so, f"servo{n}_raw") - trims[n] for n in SURFACES}
            key = (link.flightmode(), tuple(round(s / 40) for s in sticks), tuple(round(o / 40) for o in outs.values()),
                   None if att is None else (round(math.degrees(att.roll) / 10), round(math.degrees(att.pitch) / 10)))
            if key == last:
                continue
            last = key
            tilt = "" if att is None else f" | FC roll {math.degrees(att.roll):+4.0f} pitch {math.degrees(att.pitch):+4.0f} deg"
            line = (f"{time.strftime('%H:%M:%S')} {link.flightmode():6s} {'DISARMED' if _disarmed(link) else 'ARMED!'}"
                    f" | roll {sticks[0]:+5d} pitch {sticks[1]:+5d} yaw {sticks[2]:+5d} | "
                    + "  ".join(f"{SURFACES[n]} {outs[n]:+5d}" for n in SURFACES) + tilt)
            print(line, flush=True)
            lines.append(line)
    except KeyboardInterrupt:
        pass
    return dict(ok=True, trims=trims, reversed=rev, lines=lines[-200:])


def cmd_mode(link: Link, a) -> dict:
    """Set the flight mode from the laptop (disarmed only). The mode switch takes over again when it moves."""
    want = (a.arg or "").upper()
    if not want:
        raise SystemExit("usage: fc_bench.py mode MANUAL|FBWA|...")
    if not _disarmed(link):
        raise SystemExit("refusing: FC is armed")
    ok = link.set_mode(want)
    print(f"mode {want}: {'ok' if ok else 'NOT CONFIRMED'} (now {link.flightmode()})")
    return dict(ok=ok, mode=link.flightmode())


def cmd_reverse(link: Link, a) -> dict:
    """Flip SERVOn_REVERSED for one surface output (disarmed only), with read-back."""
    try:
        n = int((a.arg or "").lstrip("Ss"))
    except ValueError:
        raise SystemExit("usage: fc_bench.py reverse 3|4|5|6")
    if n not in SURFACES:
        raise SystemExit(f"S{n} isn't a surface output (S3-S6)")
    if not _disarmed(link):
        raise SystemExit("refusing: FC is armed")
    name = f"SERVO{n}_REVERSED"
    cur = params(link, [name])[name]
    new = 0.0 if cur else 1.0
    t = time.perf_counter()
    link.send("param_set_send", link.ts, 1, name.encode(), new, mavlink.MAV_PARAM_TYPE_REAL32)
    link.wait("PARAM_VALUE", lambda m: m.param_id == name, timeout=3, since=t)
    back = params(link, [name])[name]
    print(f"{name}: {cur:g} -> {back:g} ({'ok' if back == new else 'NOT CONFIRMED'})")
    return dict(ok=back == new, param=name, before=cur, after=back)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=["status", "outputs", "rc", "logs", "accel", "level", "compass", "radio",
                                        "servos", "mode", "reverse"])
    ap.add_argument("arg", nargs="?", help="mode: MANUAL/FBWA/...; reverse: output number 3-6")
    ap.add_argument("--port", help=f"default: the proxy ({PROXY}) if running, else the FC's USB port")
    ap.add_argument("--seconds", type=float, default=None, help="rc: how long to read (default 30 s); radio: longest sweep (default 180 s)")
    ap.add_argument("--manual", action="store_true", help="accel: press Enter for each position instead of auto-detect")
    ap.add_argument("--accept", action="store_true", help="compass: save a successful result")
    ap.add_argument("--yes", action="store_true", help="level/radio: no prompts")
    a = ap.parse_args(argv)
    if a.seconds is None:
        a.seconds = {"radio": 180.0, "servos": 1800.0}.get(a.command, 30.0)
    port = a.port or default_port()
    try:
        link = connect(port)
    except LinkError as e:
        raise SystemExit(f"{e} (port {port})")
    fn = dict(status=cmd_status, outputs=cmd_outputs, rc=cmd_rc, logs=cmd_logs, accel=cmd_accel, level=cmd_level,
              compass=cmd_compass, radio=cmd_radio, servos=cmd_servos, mode=cmd_mode, reverse=cmd_reverse)[a.command]
    res = fn(link, a)
    res = dict(command=a.command, port=port, time=time.strftime("%Y-%m-%dT%H:%M:%S"), result=res)
    print(f"record: {record(a.command, res)}")
    link.close()
    ok = res["result"].get("ok", True) if isinstance(res["result"], dict) else True
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
