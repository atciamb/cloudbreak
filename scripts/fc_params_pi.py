"""Check and configure the REAL flight controller through the Pi (no USB needed).

    .venv\\Scripts\\python scripts\\fc_params_pi.py backup                   # full parameter backup (read-only)
    .venv\\Scripts\\python scripts\\fc_params_pi.py audit                    # config/fc_params.toml vs the FC (read-only)
    .venv\\Scripts\\python scripts\\fc_params_pi.py apply [--yes]            # set differing [params] + [outputs]
    .venv\\Scripts\\python scripts\\fc_params_pi.py fence --site schuyler [--yes]   # upload polygon, then [fence] params

Without --yes, apply/fence only print what they would do.

How writes work: the governor key signs every message (the FC rejects anything else). The Pi forwards PARAM_SET
only inside a maintenance window: this script opens one over SSH (/run/cloudbreak-maintenance, 5 min, tmpfs) and
closes it when done. The Pi also checks that the FC's latest heartbeat says DISARMED. Every value is read back.
Link/identity parameters (SERIAL4_*, MAV_SYSID, MAV_GCS_SYSID, ARMING_*) are refused by the Pi; use USB for those.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cloudbreak.air.uplink_filter import MAINT_FLAG, param_denied  # noqa: E402
from cloudbreak.common.config import data_dir, load_toml, set_site, site  # noqa: E402
from cloudbreak.common.fence import site_fence  # noqa: E402
from cloudbreak.common.mav import GOVERNOR_SYSID, Link, load_key, mavlink  # noqa: E402

KNOWN_HOSTS = os.environ.get("CB_PI_KNOWN_HOSTS", str(data_dir() / "keys" / "known_hosts_pi"))   # follows CLOUDBREAK_DATA
SSH_KEY = str(Path.home() / ".ssh" / "cloudbreak_pi")
FC_SYSID = 42
WINDOW_S = 300


def ssh(host: str, cmd: str, timeout: float = 30.0) -> str:
    r = subprocess.run(["ssh", "-i", SSH_KEY, "-o", f"UserKnownHostsFile={KNOWN_HOSTS}", "-o", "BatchMode=yes",
                        "-o", "ConnectTimeout=8", host, cmd], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ssh failed: {r.stderr.strip()}")
    return r.stdout


def maintenance_state(host: str) -> dict:
    return json.loads(ssh(host, "cat /dev/shm/cloudbreak_pose.json")).get("stats", {}).get("maintenance", {})


class MaintenanceWindow:
    def __init__(self, host: str, seconds: int = WINDOW_S):
        self.host, self.seconds = host, seconds

    def __enter__(self):
        ssh(self.host, f"echo {time.time() + self.seconds:.0f} | sudo tee {MAINT_FLAG} >/dev/null")
        t0 = time.time()
        while time.time() - t0 < 6:
            st = maintenance_state(self.host)
            if st.get("open"):
                print(f"maintenance window open on the Pi ({st.get('left_s')} s)")
                return self
            time.sleep(0.5)
        self.__exit__(None, None, None)
        raise SystemExit(f"Pi did not open the maintenance window: {st}")

    def __exit__(self, *exc):
        ssh(self.host, f"sudo rm -f {MAINT_FLAG}")
        time.sleep(1.5)
        print(f"maintenance window closed: {maintenance_state(self.host)}")
        return False


def connect(url: str) -> Link:
    link = Link(url, GOVERNOR_SYSID, key=load_key("real"), role="rw", name="fc-params-pi")
    link.wait_heartbeat(15)
    if link.ts != FC_SYSID:
        raise SystemExit(f"refusing: heartbeat from sysid {link.ts}, expected {FC_SYSID}")
    return link


def read_param(link: Link, name: str, timeout: float = 3.0, tries: int = 3):
    for _ in range(tries):
        v = link.get_param(name, timeout=timeout)
        if v is not None:
            return v
    return None


def diff(link: Link, plan: dict) -> list[tuple[str, float | None, float]]:
    rows = []
    for k, v in plan.items():
        cur = read_param(link, k)
        rows.append((k, cur, float(v)))
    return rows


def print_rows(rows):
    for k, cur, want in rows:
        mark = "" if cur is not None and abs(cur - want) < 1e-4 else ("  (not found!)" if cur is None else "  <-- differs")
        if mark == "  <-- differs" and param_denied(k):
            mark += " (USB only)"
        print(f"  {k:18s} {cur!s:>10} -> {want:g}{mark}")


def require_disarmed(link: Link):
    hb = link.get("HEARTBEAT")
    if hb is None or hb.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
        raise SystemExit("refusing: FC is armed (or no heartbeat). Writes are bench-only, disarmed.")


def set_params(link: Link, changes: list[tuple[str, float]]) -> dict:
    out = {}
    for k, v in changes:
        t = time.perf_counter()
        link.send("param_set_send", FC_SYSID, 1, k.encode(), float(v), mavlink.MAV_PARAM_TYPE_REAL32)
        echo = link.wait("PARAM_VALUE", lambda m, k=k: m.param_id == k, timeout=3, since=t)
        back = read_param(link, k)
        ok = back is not None and abs(back - v) < 1e-4
        out[k] = dict(want=v, echo=None if echo is None else echo.param_value, readback=back, ok=ok)
        print(f"  set {k} = {v:g}: {'ok' if ok else 'NOT CONFIRMED'} (read back {back})")
    return out


def log_result(kind: str, data: dict) -> Path:
    d = data_dir() / "fc"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{kind}_pi_{time.strftime('%Y%m%dT%H%M%S')}.json"
    p.write_text(json.dumps(data, indent=2, default=str))
    return p


def cmd_backup(link: Link, a) -> int:
    from fc_setup_usb import identify_and_backup

    r = identify_and_backup(link)
    return 0 if r["total"] and len(r["params"]) >= r["total"] else 1


def cmd_audit(link: Link, a) -> int:
    cfg = load_toml("fc_params.toml")
    plan = {**cfg["params"], **cfg.get("outputs", {}), **cfg.get("radio", {})}
    if a.site:
        set_site(a.site)
    fence = site_fence(site())
    if fence is not None:
        plan.update(cfg["fence"])
        plan["FENCE_ALT_MAX"] = fence.alt_max_m
    rows = diff(link, plan)
    print_rows(rows)
    bad = [r for r in rows if r[1] is None or abs(r[1] - r[2]) > 1e-4]
    fpts = link.download_mission(mission_type=mavlink.MAV_MISSION_TYPE_FENCE)
    print(f"fence on the FC: {len(fpts)} vertices" + (f" (site {a.site or 'default'} expects {len(fence.polygon_latlon)})" if fence else ""))
    print(f"\n{len(bad)} difference(s)")
    return 0 if not bad else 1


def cmd_apply(link: Link, a) -> int:
    cfg = load_toml("fc_params.toml")
    plan = {**cfg["params"], **cfg.get("outputs", {}), **cfg.get("radio", {})}
    rows = diff(link, plan)
    print_rows(rows)
    changes = [(k, want) for k, cur, want in rows if cur is not None and abs(cur - want) > 1e-4 and not param_denied(k)]
    usb_only = [k for k, cur, want in rows if cur is not None and abs(cur - want) > 1e-4 and param_denied(k)]
    if usb_only:
        print(f"needs USB (the Pi refuses these): {usb_only}")
    if not changes:
        print("nothing to change over the Pi")
        return 0 if not usb_only else 1
    if not a.yes:
        print(f"\nDRY RUN: {len(changes)} change(s). Re-run with --yes.")
        return 0
    require_disarmed(link)
    with MaintenanceWindow(a.pi):
        res = set_params(link, changes)
    p = log_result("params", dict(changes=res))
    print(f"log: {p}")
    return 0 if all(r["ok"] for r in res.values()) else 1


def cmd_fence(link: Link, a) -> int:
    set_site(a.site)
    fence = site_fence(site())
    if fence is None:
        raise SystemExit(f"config/site_{a.site}.toml has no [fence] polygon")
    plan = dict(load_toml("fc_params.toml")["fence"])
    plan["FENCE_ALT_MAX"] = fence.alt_max_m
    plan = {k: v for k, v in plan.items() if k != "FENCE_ENABLE"} | {"FENCE_ENABLE": plan["FENCE_ENABLE"]}   # enable last
    have = link.download_mission(mission_type=mavlink.MAV_MISSION_TYPE_FENCE)
    want_pts = [(round(lat * 1e7), round(lon * 1e7)) for lat, lon in fence.polygon_latlon]
    have_pts = [(it.x, it.y) for it in have]
    poly_same = have_pts == want_pts and all(it.command == mavlink.MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION for it in have)
    print(f"site {a.site}: {len(want_pts)}-vertex polygon, ceiling {fence.alt_max_m:g} m; "
          f"FC has {len(have_pts)} fence item(s) ({'same polygon' if poly_same else 'different'})")
    rows = diff(link, plan)
    print_rows(rows)
    changes = [(k, want) for k, cur, want in rows if cur is None or abs(cur - want) > 1e-4]
    if poly_same and not changes:
        print("fence already configured")
        return 0
    if not a.yes:
        print(f"\nDRY RUN: {'upload polygon + ' if not poly_same else ''}{len(changes)} param change(s). Re-run with --yes.")
        return 0
    require_disarmed(link)
    res: dict = dict(site=a.site, polygon=fence.polygon_latlon)
    if not poly_same:
        link.upload_fence_polygon(fence.polygon_latlon)
        # ArduPilot reloads fence storage after an upload; for a moment it reports 0 items, so poll briefly
        back, ok = [], False
        for _ in range(6):
            time.sleep(1.0)
            back = link.download_mission(mission_type=mavlink.MAV_MISSION_TYPE_FENCE)
            ok = [(it.x, it.y) for it in back] == want_pts
            if ok:
                break
        res["polygon_readback_ok"] = ok
        print(f"polygon uploaded and read back: {'identical' if ok else 'MISMATCH'} ({len(back)} vertices)")
        if not ok:
            log_result("fence", res)
            return 1
    with MaintenanceWindow(a.pi):
        res["params"] = set_params(link, changes)
    time.sleep(2.0)
    ss = link.get("SYS_STATUS")
    fs = link.get("FENCE_STATUS")
    geofence = 1 << 20   # MAV_SYS_STATUS_GEOFENCE
    res["sys_status_geofence"] = None if ss is None else dict(
        present=bool(ss.onboard_control_sensors_present & geofence), enabled=bool(ss.onboard_control_sensors_enabled & geofence),
        healthy=bool(ss.onboard_control_sensors_health & geofence))
    res["fence_status"] = None if fs is None else dict(breach_status=fs.breach_status, breach_count=fs.breach_count,
                                                        breach_type=fs.breach_type, age_s=round(link.age("FENCE_STATUS"), 1))
    print(f"SYS_STATUS geofence: {res['sys_status_geofence']}; FENCE_STATUS: {res['fence_status']}")
    p = log_result("fence", res)
    print(f"log: {p}")
    return 0 if all(r["ok"] for r in res["params"].values()) else 1


def main(argv=None) -> int:
    targets = load_toml("targets.toml")
    real = targets["real"]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["backup", "audit", "apply", "fence"])
    ap.add_argument("--site", help="site key for the fence (config/site_<key>.toml)")
    ap.add_argument("--yes", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--url", default=real["governor_url"])
    ap.add_argument("--pi", default="pidrone@" + real["governor_url"].split(":")[1])
    a = ap.parse_args(argv)
    if a.command == "fence" and not a.site:
        ap.error("fence needs --site")
    link = connect(a.url)
    try:
        return dict(backup=cmd_backup, audit=cmd_audit, apply=cmd_apply, fence=cmd_fence)[a.command](link, a)
    finally:
        link.close()


if __name__ == "__main__":
    raise SystemExit(main())
