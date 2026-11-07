"""Pi-side uplink allowlist (defence in depth; the FC's signature check is the real gate).

The governor is the only ground process allowed to send to the aircraft. Its traffic reaches the FC through
the Pi bridge, which forwards a frame only if ALL hold:
  * MAVLink2 frame carrying a signature (incompat flag 0x01) -- the FC verifies it; the Pi has no key
  * source system == governor sysid (245)
  * message type in the allowlist; COMMAND_LONG/INT only for allowlisted commands; DO_SET_MODE only to
    AUTO or RTL (never MANUAL/FBWA-from-ground, never arm/disarm)
  * per-second rate limit
Everything else is dropped and counted. PARAM_SET, ARM/DISARM, RC/MANUAL overrides, SET_POSITION_TARGET_*,
FTP, reboot and motor test are never forwarded.
"""
from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass, field

GOVERNOR_SYSID = 245
MAVLINK_IFLAG_SIGNED = 0x01

# message ids (MAVLink common / ardupilotmega)
MSG = dict(HEARTBEAT=0, PARAM_REQUEST_READ=20, PARAM_REQUEST_LIST=21, MISSION_REQUEST_LIST=43, MISSION_COUNT=44,
           MISSION_CLEAR_ALL=45, MISSION_ACK=47, MISSION_SET_CURRENT=41, MISSION_REQUEST_INT=51, MISSION_ITEM_INT=73,
           COMMAND_INT=75, COMMAND_LONG=76, TIMESYNC=111,
           # explicitly denied (documented for tests)
           PARAM_SET=23, RC_CHANNELS_OVERRIDE=70, MANUAL_CONTROL=69, SET_POSITION_TARGET_LOCAL_NED=84,
           SET_POSITION_TARGET_GLOBAL_INT=86, FILE_TRANSFER_PROTOCOL=110, SET_MODE=11, SETUP_SIGNING=256,
           MISSION_ITEM=39, MISSION_REQUEST=40)

ALLOWED_MSGS = {MSG[k] for k in ("HEARTBEAT", "PARAM_REQUEST_READ", "PARAM_REQUEST_LIST", "MISSION_REQUEST_LIST",
                                 "MISSION_COUNT", "MISSION_CLEAR_ALL", "MISSION_ACK", "MISSION_SET_CURRENT",
                                 "MISSION_REQUEST_INT", "MISSION_ITEM_INT", "COMMAND_INT", "COMMAND_LONG", "TIMESYNC")}

CMD = dict(DO_SET_MODE=176, DO_SET_MISSION_CURRENT=224, DO_GO_AROUND=191, SET_MESSAGE_INTERVAL=511,
           REQUEST_MESSAGE=512,
           # denied
           COMPONENT_ARM_DISARM=400, PREFLIGHT_REBOOT_SHUTDOWN=246, DO_MOTOR_TEST=209, DO_SET_SERVO=183,
           PREFLIGHT_CALIBRATION=241, DO_FLIGHTTERMINATION=185, DO_SET_PARAMETER=180, NAV_TAKEOFF=22)
ALLOWED_CMDS = {CMD[k] for k in ("DO_SET_MODE", "DO_SET_MISSION_CURRENT", "DO_GO_AROUND", "SET_MESSAGE_INTERVAL",
                                 "REQUEST_MESSAGE")}
PLANE_MODE = dict(MANUAL=0, CIRCLE=1, STABILIZE=2, FBWA=5, FBWB=6, AUTO=10, RTL=11, LOITER=12, GUIDED=15)
ALLOWED_MODES = {PLANE_MODE["AUTO"], PLANE_MODE["RTL"]}


@dataclass
class Verdict:
    forward: bool
    reason: str


@dataclass
class UplinkFilter:
    governor_sysid: int = GOVERNOR_SYSID
    max_per_s: int = 60
    stats: Counter = field(default_factory=Counter)
    _times: deque = field(default_factory=deque)

    def check(self, msg) -> Verdict:
        """`msg` is a parsed pymavlink message (from the governor's TCP stream)."""
        mid = msg.get_msgId()
        hdr = msg.get_header()
        signed = bool(getattr(hdr, "incompat_flags", 0) & MAVLINK_IFLAG_SIGNED)
        if not signed:
            return self._deny("unsigned")
        if msg.get_srcSystem() != self.governor_sysid:
            return self._deny(f"sysid {msg.get_srcSystem()}")
        if mid not in ALLOWED_MSGS:
            return self._deny(f"msg {msg.get_type()}")
        if mid in (MSG["COMMAND_LONG"], MSG["COMMAND_INT"]):
            if msg.command not in ALLOWED_CMDS:
                return self._deny(f"cmd {msg.command}")
            if msg.command == CMD["DO_SET_MODE"] and int(msg.param2) not in ALLOWED_MODES:
                return self._deny(f"mode {int(msg.param2)}")
        now = time.monotonic()
        self._times.append(now)
        while self._times and now - self._times[0] > 1.0:
            self._times.popleft()
        if len(self._times) > self.max_per_s:
            return self._deny("rate")
        self.stats["forwarded"] += 1
        return Verdict(True, "ok")

    def _deny(self, why: str) -> Verdict:
        self.stats[f"dropped:{why.split()[0]}"] += 1
        return Verdict(False, why)
