"""SITL-only stand-in for the human pilot's RC actions (arming, mode switch, throttle-up abort).

On the real aircraft these are done by the pilot on the Pocket transmitter; the governor never arms, never
sends RC overrides. Here: when the governor reports a loaded survey mission ('surveying'), arm and switch to
AUTO so SITL takes off and flies it.
    .venv\\Scripts\\python sim\\sim_pilot.py [--throttle-abort]
"""
import argparse
import time

import httpx

from cloudbreak.common.mav import GOVERNOR_SYSID, Link, load_key, mavlink

ap = argparse.ArgumentParser()
ap.add_argument("--throttle-abort", action="store_true", help="push throttle >90%% once on short final")
a = ap.parse_args()
pilot = Link("tcp:127.0.0.1:5765", GOVERNOR_SYSID, compid=191, role="ro", key=load_key("sitl"), name="sim_pilot")
pilot.wait_heartbeat(60)
print("[sim_pilot] ready (SITL only)", flush=True)
armed_for = None
while True:
    time.sleep(1.0)
    try:
        g = httpx.get("http://127.0.0.1:8710/api/status", timeout=1).json()
    except Exception:
        continue
    m = g.get("mission") or {}
    hb = pilot.get("HEARTBEAT")
    armed = bool(hb and hb.base_mode & 128)
    if g.get("state") == "surveying" and m.get("hash") != armed_for:
        if not armed:
            pilot.set_mode("FBWA")
            for _ in range(15):
                if pilot.command_long(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1, timeout=2) == 0:
                    break
                time.sleep(2)
        pilot.set_mode("AUTO")            # the pilot flips the mode switch to AUTO for the survey
        armed_for = m.get("hash")
        print(f"[sim_pilot] AUTO for survey {m.get('hash', '')[:8]} (was armed: {armed})", flush=True)
    if a.throttle_abort and g.get("state") == "committed":
        gpi = pilot.get("GLOBAL_POSITION_INT")
        if gpi and gpi.relative_alt < 10000 and g.get("mission_current") == m.get("seq", {}).get("touchdown"):
            for _ in range(8):
                pilot.send("rc_channels_override_send", pilot.ts, 1, 0, 0, 1950, 0, 0, 0, 0, 0)
                time.sleep(0.25)
            pilot.send("rc_channels_override_send", pilot.ts, 1, 0, 0, 0, 0, 0, 0, 0, 0)
            print("[sim_pilot] throttle-up abort", flush=True)
            a.throttle_abort = False
