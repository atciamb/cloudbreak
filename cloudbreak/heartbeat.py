"""Wait for a MAVLink heartbeat from an autopilot and print what it reports.

A read-only link check for the Pi <-> flight controller UART or for ArduPlane
SITL. It only listens; it never sends commands to the vehicle.

Examples:
    python -m cloudbreak.heartbeat --device tcp:127.0.0.1:5760
    python -m cloudbreak.heartbeat --device /dev/serial0 --baud 115200
"""

import argparse
import os
import sys
import time

# The FC's companion port is set to MAVLink2; make pymavlink parse v2 frames.
os.environ.setdefault("MAVLINK20", "1")

from pymavlink import mavutil  # noqa: E402


def wait_for_autopilot(conn, timeout):
    """Return the first HEARTBEAT from an autopilot, or None on timeout.

    Heartbeats from ground stations (e.g. a laptop GCS on the same link) are
    skipped, because they report MAV_AUTOPILOT_INVALID.
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=remaining)
        if msg is None:
            return None
        if msg.autopilot != mavutil.mavlink.MAV_AUTOPILOT_INVALID:
            return msg


def describe(msg):
    """Return a short human-readable summary of a HEARTBEAT message."""
    armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
    autopilot = mavutil.mavlink.enums["MAV_AUTOPILOT"][msg.autopilot].name
    vehicle = mavutil.mavlink.enums["MAV_TYPE"][msg.type].name
    return (
        f"system {msg.get_srcSystem()}, component {msg.get_srcComponent()}\n"
        f"  autopilot: {autopilot}\n"
        f"  vehicle:   {vehicle}\n"
        f"  mode:      {mavutil.mode_string_v10(msg)}\n"
        f"  armed:     {'YES' if armed else 'no'}"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--device",
        default="tcp:127.0.0.1:5760",
        help="pymavlink connection string, e.g. /dev/serial0 or tcp:127.0.0.1:5760",
    )
    parser.add_argument("--baud", type=int, default=115200, help="serial baud rate")
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds to wait")
    args = parser.parse_args(argv)

    print(f"Listening on {args.device} (baud {args.baud}) for up to {args.timeout:.0f} s...")
    conn = mavutil.mavlink_connection(args.device, baud=args.baud)
    try:
        msg = wait_for_autopilot(conn, args.timeout)
    finally:
        conn.close()

    if msg is None:
        print(
            "No autopilot heartbeat received. Check wiring (TX->RX, RX->TX, shared GND), "
            "baud rate, and that the FC port is set to MAVLink2.",
            file=sys.stderr,
        )
        return 1

    print("Heartbeat received from " + describe(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
