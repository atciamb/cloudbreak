"""Install the SITL MAVLink2 signing key (stands in for installing the real key on the FC over USB).
After this, SITL ignores unsigned commands on non-USB ports; telemetry still flows to unsigned readers.
    .venv\\Scripts\\python sim\\sitl\\setup_signing.py
"""
import time

from cloudbreak.common.mav import GOVERNOR_SYSID, Link, install_signing_key, load_key, mavlink

key = load_key("sitl")
l = Link("tcp:127.0.0.1:5762", GOVERNOR_SYSID, role="ro", name="setup")
l.wait_heartbeat(60)
install_signing_key(l, key)
time.sleep(1.0)
l.m.setup_signing(key, sign_outgoing=True)
ack = l.command_long(mavlink.MAV_CMD_REQUEST_MESSAGE, mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION, timeout=2)
print("signing installed; signed command ack =", ack)
l.close()
