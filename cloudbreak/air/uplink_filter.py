"""Pi-side uplink allowlist (defence in depth; the FC's signature check is the real gate).

The governor is the only ground process allowed to send to the aircraft. Its traffic reaches the FC through
the Pi bridge, which forwards a frame only if ALL hold:
  * MAVLink2 frame carrying a signature (incompat flag 0x01) -- the FC verifies it; the Pi has no key
  * source system == governor sysid (245)
  * message type in the allowlist; COMMAND_LONG/INT only for allowlisted commands; DO_SET_MODE only to
    AUTO or RTL (never MANUAL/FBWA-from-ground, never arm/disarm)
  * per-second rate limit
Everything else is dropped and counted. ARM/DISARM, RC/MANUAL overrides, SET_POSITION_TARGET_*, FTP, reboot and
motor test are never forwarded.

PARAM_SET is forwarded ONLY in a maintenance window, which needs all of these:
  * someone with SSH access wrote an expiry time into /run/cloudbreak-maintenance (tmpfs: gone after a reboot),
    and the window is at most MAINT_MAX_S long;
  * the FC's latest heartbeat (< 3 s old) says DISARMED;
  * the parameter is not one that could cut this link or weaken arming (MAINT_DENY_PARAMS).
The FC still checks the signature, so only the governor's key can change anything.
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

MAINT_FLAG = "/run/cloudbreak-maintenance"
MAINT_MAX_S = 900.0
HB_FRESH_S = 3.0
# never settable over the air: these could sever the Pi link, change who the FC trusts, or weaken arming checks
MAINT_DENY_PREFIXES = ("SERIAL4_", "MAV3_", "ARMING_", "BRD_SER4", "BRD_SAFETY", "SCR_", "FORMAT_")
MAINT_DENY_PARAMS = {"MAV_SYSID", "SYSID_THISMAV", "MAV_GCS_SYSID", "SYSID_MYGCS", "BRD_OPTIONS"}


def param_denied(name: str) -> bool:
    return name in MAINT_DENY_PARAMS or name.startswith(MAINT_DENY_PREFIXES)


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
    # set by the bridge: wall-clock expiry of the maintenance window, and the FC's armed state + when it was seen
    maintenance_until: float = 0.0
    fc_armed: bool | None = None
    fc_hb_mono: float = 0.0

    def maintenance_open(self, now_wall: float | None = None, now_mono: float | None = None) -> str | None:
        """None if a PARAM_SET may pass right now, else the reason it may not."""
        now_wall = time.time() if now_wall is None else now_wall
        now_mono = time.monotonic() if now_mono is None else now_mono
        if not (now_wall < self.maintenance_until <= now_wall + MAINT_MAX_S):
            return "no-window"
        if self.fc_armed is None or now_mono - self.fc_hb_mono > HB_FRESH_S:
            return "no-fresh-heartbeat"
        if self.fc_armed:
            return "armed"
        return None

    def check(self, msg) -> Verdict:
        """`msg` is a parsed pymavlink message (from the governor's TCP stream)."""
        mid = msg.get_msgId()
        hdr = msg.get_header()
        signed = bool(getattr(hdr, "incompat_flags", 0) & MAVLINK_IFLAG_SIGNED)
        if not signed:
            return self._deny("unsigned")
        if msg.get_srcSystem() != self.governor_sysid:
            return self._deny(f"sysid {msg.get_srcSystem()}")
        if mid == MSG["PARAM_SET"]:
            why = self.maintenance_open()
            if why is not None:
                return self._deny("msg PARAM_SET" if why == "no-window" else f"param {why}")
            name = msg.param_id if isinstance(msg.param_id, str) else msg.param_id.decode(errors="replace")
            if param_denied(name):
                return self._deny(f"param denied {name}")
            self.stats["forwarded:param_set"] += 1
            return self._rate_ok()
        if mid not in ALLOWED_MSGS:
            return self._deny(f"msg {msg.get_type()}")
        if mid in (MSG["COMMAND_LONG"], MSG["COMMAND_INT"]):
            if msg.command not in ALLOWED_CMDS:
                return self._deny(f"cmd {msg.command}")
            if msg.command == CMD["DO_SET_MODE"] and int(msg.param2) not in ALLOWED_MODES:
                return self._deny(f"mode {int(msg.param2)}")
        return self._rate_ok()

    def _rate_ok(self) -> Verdict:
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
