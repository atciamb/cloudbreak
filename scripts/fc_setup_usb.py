"""Configure the REAL flight controller over USB for Cloudbreak (dry run by default).

    .venv\\Scripts\\python scripts\\fc_setup_usb.py --port COM5            # dry run: read + show the diff
    .venv\\Scripts\\python scripts\\fc_setup_usb.py --port COM5 --apply    # write params, verify, install signing key

What it sets (ArduPlane 4.7.2 names, verified in SITL):
  * Pi link on SERIAL4 (UART4 T4/R4): MAVLink2 @115200, stream rates on the matching MAVn instance
  * identity: MAV_SYSID=42 (4.7 name for SYSID_THISMAV); only the governor (sysid 245) counts as GCS for the GCS failsafe
  * no airspeed sensor; throttle-up landing abort; RC + GCS failsafes -> RTL; RTL never auto-lands
  * MAVLink2 signing key (C:\\cb-data\\keys\\mavlink_real.key) -- after this, only signed commands are accepted on
    non-USB ports (i.e. through the Pi). USB stays open for setup/recovery.
It does NOT touch control tuning, servo outputs, mode switches or arming checks. The desired values live in
config/fc_params.toml. Normal setup and the geofence go through the Pi (scripts/fc_params_pi.py). This USB script
is for recovery and for the link/identity parameters the Pi refuses to change (SERIAL4_*, MAV_SYSID, signing key).
Prop OFF and battery handling per the team's power-on rules while doing this.
"""
from __future__ import annotations

import argparse
import sys
import time

from cloudbreak.common.mav import GCS_COMPID, Link, install_signing_key, load_key, mavlink

from cloudbreak.common.config import load_toml  # noqa: E402

# single source of truth, shared with scripts/fc_params_pi.py (SERIAL4_BAUD comes from --baud here)
PARAMS = {k: v for k, v in load_toml("fc_params.toml")["params"].items() if k != "SERIAL4_BAUD"}
STREAMS = {"EXTRA1": 20, "POSITION": 10, "EXTRA2": 5, "EXTRA3": 2, "EXT_STAT": 4, "RC_CHAN": 4, "RAW_SENS": 2}


def mav_instance_for_serial(link: Link, serial_n: int) -> int | None:
    """MAVn instances are assigned in order of MAVLink-enabled serial ports (SERIAL0=USB is MAV1)."""
    order = []
    for n in range(0, 8):
        p = link.get_param(f"SERIAL{n}_PROTOCOL", timeout=2)
        if p is None:
            continue
        if int(p) in (1, 2):
            order.append(n)
    if serial_n in order:
        return order.index(serial_n) + 1
    return None


def identify_and_backup(link: Link) -> dict:
    """Read-only: firmware/board banner + AUTOPILOT_VERSION, then a FULL parameter backup to C:\\cb-data\\fc\\."""
    from cloudbreak.common.config import data_dir

    t0 = time.perf_counter()
    link.command_long(mavlink.MAV_CMD_REQUEST_MESSAGE, mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION, timeout=2)
    link.command_long(42428, timeout=2)                         # MAV_CMD_DO_SEND_BANNER
    time.sleep(1.5)
    banner = [m.text for tt, m in list(link._inbox) if tt >= t0 and m.get_type() == "STATUSTEXT"]
    av = link.get("AUTOPILOT_VERSION")
    fw = None
    if av is not None:
        v = av.flight_sw_version
        fw = f"{(v >> 24) & 255}.{(v >> 16) & 255}.{(v >> 8) & 255} (type {v & 255})"
    print("firmware:", fw)
    for line in banner:
        print("  banner:", line)
    # full parameter list: collect EVERY PARAM_VALUE from the receive buffer (dedupe by index), then re-request
    # missing indices in batches until complete.
    start = time.perf_counter()
    by_idx: dict[int, tuple[str, float]] = {}
    total = None

    def harvest():
        nonlocal total
        new = 0
        for tt, m in list(link._inbox):
            if tt >= start and m.get_type() == "PARAM_VALUE" and m.param_index < 65535 and m.param_index not in by_idx:
                by_idx[m.param_index] = (m.param_id, m.param_value)
                total = m.param_count
                new += 1
        return new

    link.send("param_request_list_send", link.ts, 1)
    last_new = time.perf_counter()
    while time.perf_counter() - last_new < 3.0 and not (total and len(by_idx) >= total):
        time.sleep(0.2)
        if harvest():
            last_new = time.perf_counter()
    for _ in range(6):
        if not total or len(by_idx) >= total:
            break
        missing = [i for i in range(total) if i not in by_idx]
        for k in range(0, len(missing), 20):
            for i in missing[k:k + 20]:
                link.send("param_request_read_send", link.ts, 1, b"", i)
            time.sleep(0.4)
            harvest()
        time.sleep(0.5)
        harvest()
    params = {name: val for name, val in by_idx.values()}
    out = data_dir() / "fc"
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"params_backup_{time.strftime('%Y%m%dT%H%M%S')}.parm"
    p.write_text(f"# FC parameter backup {time.ctime()} firmware {fw}\n" + "".join(f"# {b}\n" for b in banner) +
                 "".join(f"{k},{v:.6g}\n" for k, v in sorted(params.items())))
    print(f"backup: {len(params)}/{total} params -> {p}")
    if total and len(params) < total:
        print("WARNING: backup incomplete -- re-run before --apply")
    return dict(firmware=fw, banner=banner, params=params, total=total, path=str(p))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="USB serial port of the FC, e.g. COM5")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-signing", action="store_true")
    ap.add_argument("--baud", type=int, default=230, help="SERIAL4_BAUD code (230 = 230400, 115 = 115200); must match the Pi")
    a = ap.parse_args(argv)
    link = Link(a.port, 245, compid=GCS_COMPID, role="ro", name="fc-usb")
    hb = link.wait_heartbeat(30)
    print(f"connected: sysid {link.target_system} type {hb.type} autopilot {hb.autopilot}")
    if link.get_param("SIM_SPEEDUP", timeout=2) is not None:
        sys.exit("refusing: this is SITL (SIM_* params present), not the real FC")
    identify_and_backup(link)
    plan = dict(PARAMS)
    plan["SERIAL4_BAUD"] = a.baud
    # SERIAL4 may not be MAVLink yet, so compute the stream instance as if it were
    cur4 = link.get_param("SERIAL4_PROTOCOL")
    inst = mav_instance_for_serial(link, 4)
    if inst is None:
        # if SERIAL4 isn't MAVLink yet, it will become the next instance after existing ones
        ports = [n for n in range(8) if (link.get_param(f"SERIAL{n}_PROTOCOL", timeout=1) or 0) in (1, 2) and n < 4]
        inst = len(ports) + 1
    for k, v in STREAMS.items():
        plan[f"MAV{inst}_{k}"] = v
    plan[f"MAV{inst}_OPTIONS"] = 4          # bit2: ignore stream-rate requests from GCS
    print(f"SERIAL4 currently protocol {cur4}; streams go to MAV{inst}_* (verify after reboot)")
    changes = []
    for k, v in plan.items():
        cur = link.get_param(k, timeout=2)
        mark = "" if cur is not None and abs(cur - v) < 1e-4 else "  <-- change"
        if cur is None:
            mark = "  (param not found!)"
        print(f"  {k:22s} {cur!s:>10} -> {v}{mark}")
        if mark == "  <-- change":
            changes.append((k, v))
    if not a.apply:
        print(f"\nDRY RUN: {len(changes)} change(s). Re-run with --apply after the team agrees.")
        return
    for k, v in changes:
        t = time.perf_counter()
        link.send("param_set_send", link.ts, 1, k.encode(), float(v), mavlink.MAV_PARAM_TYPE_REAL32)
        echo = link.wait("PARAM_VALUE", lambda m, k=k: m.param_id == k, timeout=3, since=t)
        print(f"  set {k}={v}: {'ok' if echo is not None and abs(echo.param_value - v) < 1e-4 else 'NOT CONFIRMED'}")
    if not a.no_signing:
        install_signing_key(link, load_key("real"))
        print("signing key installed (non-USB ports now require signed commands). Reboot the FC to apply serial changes.")


if __name__ == "__main__":
    main()
