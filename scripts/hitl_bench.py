"""HITL bench test of the real command path: laptop -> Pi bridge (TCP :14560) -> FC UART4 (SERIAL4).

Props off, battery unplugged. It never arms, never changes mode and never writes a parameter. The only write is a
short test mission, and the FC's previous mission is restored afterwards (or cleared if there was none).

Checks:
  T1  signed link up: heartbeat from sysid 42; telemetry ages and sequence loss
  T2  signed PARAM_REQUEST_READ round trips: RTT stats, plus the [real.param_audit] values from config/targets.toml
  T3  signed mission upload -> read-back -> canonical hash match; then restore
  T4  unsigned request through the Pi           -> dropped at the Pi ("unsigned"), no reply
  T5  request signed with a WRONG key           -> forwarded by the Pi (it has no key), ignored by the FC
  T6  correct key but sysid 200                  -> dropped at the Pi ("sysid"), no reply
  T7  signed PARAM_SET (same value)              -> dropped at the Pi ("msg"), no echo
  T8  signed DO_SET_MODE MANUAL (only if already MANUAL, so it is harmless even if forwarded) -> dropped ("mode")
  T9  positive controls: the same param names as T4-T6, requested correctly, do get replies
  T10 (with --direct) unsigned request straight onto the FC UART from the Pi, bypassing the filter -> ignored by the FC

Usage:
    .venv\\Scripts\\python scripts\\hitl_bench.py [--direct]
Evidence goes to C:\\cb-data\\hitl\\hitl_<time>.json.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import statistics
import subprocess
import sys
import time
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudbreak.common.config import data_dir  # noqa: E402
from cloudbreak.common.mav import GOVERNOR_SYSID, Link, MissionItem, load_key, mavlink, mission_hash  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
KNOWN_HOSTS = os.environ.get("CB_PI_KNOWN_HOSTS", r"C:\cb-data\keys\known_hosts_pi")
SSH_KEY = str(Path.home() / ".ssh" / "cloudbreak_pi")
FC_SYSID = 42
WINDOW_S = 3.0


def ssh(host: str, cmd: str, timeout: float = 60.0) -> str:
    r = subprocess.run(["ssh", "-i", SSH_KEY, "-o", f"UserKnownHostsFile={KNOWN_HOSTS}", "-o", "BatchMode=yes",
                        "-o", "ConnectTimeout=8", host, cmd], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ssh failed: {r.stderr.strip()}")
    return r.stdout


def pi_uplink_stats(host: str) -> dict:
    snap = json.loads(ssh(host, "cat /dev/shm/cloudbreak_pose.json"))
    return dict(snap.get("stats", {}).get("uplink", {}))


def counter_diff(a: dict, b: dict) -> dict:
    return {k: b.get(k, 0) - a.get(k, 0) for k in sorted(set(a) | set(b)) if b.get(k, 0) != a.get(k, 0)}


def request_param(link: Link, name: str) -> float:
    """Send PARAM_REQUEST_READ on `link`; return the send time (perf_counter)."""
    t = time.perf_counter()
    link.send("param_request_read_send", FC_SYSID, 1, name.encode(), -1)
    return t


def param_reply(observer: Link, name: str, since: float, timeout: float = WINDOW_S):
    return observer.wait("PARAM_VALUE", lambda m: m.param_id == name, timeout=timeout, since=since)


def test_mission() -> list[MissionItem]:
    # three waypoints over Schuyler Flatts at 40 m; never executed (the FC stays in MANUAL, disarmed)
    wp = mavlink.MAV_CMD_NAV_WAYPOINT
    return [MissionItem(wp, lat=42.70640, lon=-73.71000, alt=40.0, label="hitl-1"),
            MissionItem(wp, lat=42.70700, lon=-73.71000, alt=40.0, label="hitl-2"),
            MissionItem(wp, lat=42.70700, lon=-73.70920, alt=40.0, label="hitl-3")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    targets = tomllib.loads((ROOT / "config" / "targets.toml").read_text())
    real = targets["real"]
    ap.add_argument("--url", default=real["governor_url"])
    ap.add_argument("--pi", default="pidrone@" + real["governor_url"].split(":")[1])
    ap.add_argument("--direct", action="store_true", help="also run T10 (briefly stops the Pi bridge)")
    a = ap.parse_args(argv)

    res: dict = dict(started=time.strftime("%Y-%m-%dT%H:%M:%S"), url=a.url, pi=a.pi, tests={})
    T = res["tests"]

    def verdict(name: str, ok: bool, **info):
        T[name] = dict(ok=bool(ok), **info)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {json.dumps(info, default=str)}")

    stats0 = pi_uplink_stats(a.pi)
    gov = Link(a.url, GOVERNOR_SYSID, key=load_key("real"), role="rw", name="hitl-gov")
    others: list[Link] = []
    orig_items = None
    try:
        hb = gov.wait_heartbeat(15)
        time.sleep(2.0)                                   # let telemetry settle for age/loss numbers
        armed = bool(hb.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        mode = gov.flightmode()
        ages = {k: round(gov.age(k), 3) for k in ("HEARTBEAT", "ATTITUDE", "GLOBAL_POSITION_INT", "SYS_STATUS")}
        verdict("T1_signed_link", gov.ts == FC_SYSID and not armed and ages["HEARTBEAT"] < 2.0,
                sysid=gov.ts, mode=mode, armed=armed, telemetry_age_s=ages,
                seq_loss=round(gov.autopilot_loss_rate(), 4))
        if armed:
            raise SystemExit("FC is ARMED - stopping. This bench test runs disarmed only.")

        # T2: RTT + parameter audit (read-only)
        audit = dict(real.get("param_audit", {}))
        names = list(audit) + ["WP_RADIUS"]
        rtts, values = [], {}
        for name in names:
            t = request_param(gov, name)
            msg = param_reply(gov, name, t)
            if msg is not None:
                rtts.append((time.perf_counter() - t) * 1000)  # upper bound: includes wait() wake-up
                values[name] = msg.param_value
        mism = {k: dict(expected=v[0], got=values.get(k)) for k, v in audit.items()
                if values.get(k) is None or abs(values[k] - v[0]) > v[1]}
        verdict("T2_rtt_and_param_read", len(rtts) == len(names),
                replies=f"{len(rtts)}/{len(names)}",
                rtt_ms=dict(min=round(min(rtts), 1), median=round(statistics.median(rtts), 1),
                            max=round(max(rtts), 1)) if rtts else None,
                max_rtt_allowed_ms=real.get("max_rtt_ms"))
        res["param_audit"] = dict(values=values, mismatches=mism)
        print(f"       param audit mismatches (the governor would refuse an upload): {mism or 'none'}")

        # T3: signed mission upload + read-back hash, then restore
        orig_items = gov.download_mission()
        items = test_mission()
        h_sent = mission_hash(items)
        t0 = time.perf_counter()
        gov.upload_mission(items)
        t_up = time.perf_counter() - t0
        back = gov.download_mission()
        h_back = mission_hash(back)
        verdict("T3_mission_upload_readback", h_back == h_sent, items=len(items), upload_s=round(t_up, 2),
                hash_sent=h_sent[:16], hash_readback=h_back[:16], previous_mission_items=len(orig_items))

        # T4-T6: requests that must NOT get an answer (each uses its own parameter name)
        u = Link(a.url, GOVERNOR_SYSID, key=None, role="ro", name="hitl-unsigned"); others.append(u)
        w = Link(a.url, GOVERNOR_SYSID, key=secrets.token_bytes(32), role="ro", name="hitl-wrongkey"); others.append(w)
        s = Link(a.url, 200, key=load_key("real"), role="ro", name="hitl-sysid200"); others.append(s)
        u.wait_heartbeat(10)
        s.wait_heartbeat(10)
        time.sleep(1.0)    # w can't decode the FC's correctly signed telemetry, so it never sees a heartbeat; just let it connect
        cases = [("T4_unsigned_dropped_at_pi", u, "WP_LOITER_RAD"),
                 ("T5_wrong_key_ignored_by_fc", w, "RTL_RADIUS"),
                 ("T6_wrong_sysid_dropped_at_pi", s, "WP_MAX_RADIUS")]
        for name, link, pname in cases:
            before = pi_uplink_stats(a.pi)
            t = request_param(link, pname)
            reply = param_reply(gov, pname, t)
            time.sleep(0.3)
            verdict(name, reply is None, param=pname, reply=None if reply is None else reply.param_value,
                    pi_filter=counter_diff(before, pi_uplink_stats(a.pi)))

        # T7: signed PARAM_SET of the value already stored -> must be dropped at the Pi
        cur = values.get("WP_RADIUS")
        if cur is not None:
            before = pi_uplink_stats(a.pi)
            t = time.perf_counter()
            gov.send("param_set_send", FC_SYSID, 1, b"WP_RADIUS", float(cur), mavlink.MAV_PARAM_TYPE_REAL32)
            echo = param_reply(gov, "WP_RADIUS", t)
            time.sleep(0.3)
            verdict("T7_param_set_dropped_at_pi", echo is None, value_sent=cur,
                    pi_filter=counter_diff(before, pi_uplink_stats(a.pi)))

        # T8: DO_SET_MODE MANUAL -> must be dropped at the Pi (only tried when already MANUAL)
        if gov.flightmode() == "MANUAL":
            before = pi_uplink_stats(a.pi)
            t = time.perf_counter()
            gov.send("command_long_send", FC_SYSID, 1, mavlink.MAV_CMD_DO_SET_MODE, 0,
                     mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 0, 0, 0, 0, 0, 0)
            ack = gov.wait("COMMAND_ACK", lambda m: m.command == mavlink.MAV_CMD_DO_SET_MODE, timeout=WINDOW_S, since=t)
            time.sleep(0.3)
            verdict("T8_manual_mode_dropped_at_pi", ack is None, ack=None if ack is None else ack.result,
                    pi_filter=counter_diff(before, pi_uplink_stats(a.pi)))
        else:
            T["T8_manual_mode_dropped_at_pi"] = dict(ok=None, skipped=f"FC mode is {gov.flightmode()}, not MANUAL")

        # T9: positive controls -- the same names requested correctly do answer
        got = {}
        for _, _, pname in cases:
            t = request_param(gov, pname)
            m = param_reply(gov, pname, t)
            got[pname] = None if m is None else m.param_value
        verdict("T9_positive_controls", all(v is not None for v in got.values()), values=got)
    finally:
        for l in others:
            l.close()
        if orig_items is not None:
            try:
                if orig_items:
                    gov.upload_mission(orig_items)
                    ok = mission_hash(gov.download_mission()) == mission_hash(orig_items)
                else:
                    t = time.perf_counter()
                    gov.send("mission_clear_all_send", FC_SYSID, 1, 0)
                    gov.wait("MISSION_ACK", timeout=4.0, since=t)
                    ok = gov.download_mission() == []
                res["mission_restored"] = dict(ok=ok, items=len(orig_items))
                print(f"[{'PASS' if ok else 'FAIL'}] mission restored to its previous {len(orig_items)} item(s)")
            except Exception as e:                     # noqa: BLE001
                res["mission_restored"] = dict(ok=False, error=str(e))
                print(f"[FAIL] mission restore: {e}  -> clear it before any AUTO flight")
        gov.close()

    res["pi_uplink_filter_total"] = counter_diff(stats0, pi_uplink_stats(a.pi))

    if a.direct:
        # T10: bypass the Pi filter: unsigned PARAM_REQUEST_READ straight onto the FC UART
        script = r'''
import json, time
from pymavlink import mavutil
m = mavutil.mavlink_connection("/dev/serial0", baud=230400, source_system=245, source_component=190)
hb = m.wait_heartbeat(timeout=10)
def ask(name):
    m.mav.param_request_read_send(42, 1, name.encode(), -1)
    t = time.time()
    while time.time() - t < 3:
        msg = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.5)
        if msg is not None and msg.param_id == name:
            return msg.param_value
    return None
print(json.dumps(dict(heartbeat=hb is not None, unsigned_reply=ask("WP_LOITER_RAD"))))
'''
        out = ssh(a.pi, "trap 'sudo systemctl start cloudbreak-mavbridge' EXIT; sudo systemctl stop cloudbreak-mavbridge; "
                        f"sudo /opt/cloudbreak/venv/bin/python -c '{script.replace(chr(39), chr(34))}'", timeout=90)
        d = json.loads(out.strip().splitlines()[-1])
        ok = d["heartbeat"] and d["unsigned_reply"] is None
        T["T10_unsigned_direct_ignored_by_fc"] = dict(ok=ok, **d)
        print(f"[{'PASS' if ok else 'FAIL'}] T10_unsigned_direct_ignored_by_fc: {d}")

    res["all_pass"] = all(v.get("ok") is not False for v in T.values()) and res.get("mission_restored", {}).get("ok", True)
    out_dir = Path(data_dir()) / "hitl"
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"hitl_{time.strftime('%Y%m%dT%H%M%S')}.json"
    p.write_text(json.dumps(res, indent=2, default=str))
    print(f"\n{'ALL PASS' if res['all_pass'] else 'SOME CHECKS FAILED'} -> {p}")
    return 0 if res["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
