"""MAVLink plumbing shared by core (read-only), governor (read-write, signed), sim tools and tests.

* One `Link` = one MAVLink connection + a receive thread that keeps the latest message of each type,
  a short inbox for protocol waits, and per-source sequence-gap statistics.
* Mission items are `MissionItem` (MISSION_ITEM_INT semantics). `mission_hash` is computed over a
  canonical encoding that survives the float32 / int32 round-trip through the autopilot, so an upload
  can be verified by downloading it again and comparing hashes.
* Signing: `Link(..., key=bytes32)` signs every outgoing message (MAVLink2 signing). ArduPilot ignores
  unsigned commands on non-USB ports once a key is installed; telemetry still flows to unsigned readers.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

os.environ.setdefault("MAVLINK20", "1")
from pymavlink import mavutil  # noqa: E402

mavlink = mavutil.mavlink

GOVERNOR_SYSID = 245      # the only sysid the autopilot accepts as "the GCS" (MAV_GCS_SYSID)
CORE_SYSID = 250          # read-only observer
SIM_PILOT_SYSID = 240     # SITL-only stand-in for the human pilot's RC
GCS_COMPID = mavlink.MAV_COMP_ID_MISSIONPLANNER

FRAME_REL_ALT_INT = mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT


def load_key(target: str) -> bytes:
    from cloudbreak.common.config import data_dir

    p = Path(data_dir()) / "keys" / f"mavlink_{target}.key"
    k = p.read_bytes()
    if len(k) != 32:
        raise ValueError(f"{p} must hold exactly 32 bytes")
    return k


# ----------------------------------------------------------------------------- mission items
@dataclass
class MissionItem:
    command: int
    frame: int = FRAME_REL_ALT_INT
    param1: float = 0.0
    param2: float = 0.0
    param3: float = 0.0
    param4: float = 0.0
    lat: float = 0.0          # degrees
    lon: float = 0.0          # degrees
    alt: float = 0.0          # metres (relative to home for FRAME_REL_ALT_INT)
    autocontinue: int = 1
    label: str = ""           # human-readable role, not sent

    @property
    def x(self) -> int:
        return int(round(self.lat * 1e7))

    @property
    def y(self) -> int:
        return int(round(self.lon * 1e7))

    def to_dict(self):
        d = asdict(self)
        d["command_name"] = mavlink.enums["MAV_CMD"][self.command].name if self.command in mavlink.enums["MAV_CMD"] else str(self.command)
        return d


def _f32(v: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(v)))[0]


# ArduPilot 4.7.2 read-back normalisation, verified against SITL (docs/sitl_notes.md):
#   *_INT frames come back as their float equivalents; command-only items come back in frame 0;
#   NAV_LOITER_TO_ALT param1 (heading-required; Plane always exits on heading) is dropped;
#   NAV_LAND param4 is rewritten by the autopilot. Only these fields are normalised/ignored.
_FRAME_CANON = {5: 0, 6: 3, 11: 10, 2: 0}
_IGNORED_PARAMS = {31: (0,), 21: (3,)}   # MAV_CMD -> zero-based param indices ignored in the hash


def canonical_items(items: Iterable[MissionItem]) -> list[list]:
    """Encoding that is invariant under the autopilot round-trip (float32 params, int32 lat/lon)."""
    out = []
    for it in items:
        params = [float(f"{_f32(p):.6g}") for p in (it.param1, it.param2, it.param3, it.param4)]
        for i in _IGNORED_PARAMS.get(int(it.command), ()):
            params[i] = 0.0
        out.append([
            int(it.command), _FRAME_CANON.get(int(it.frame), int(it.frame)), *params,
            it.x, it.y, round(_f32(it.alt), 2), int(it.autocontinue),
        ])
    return out


def mission_hash(items: Iterable[MissionItem]) -> str:
    """SHA-256 over canonical items with seq >= 1 (ArduPilot rewrites seq 0 = home)."""
    blob = json.dumps(canonical_items(items), separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def item_from_msg(msg) -> MissionItem:
    return MissionItem(command=msg.command, frame=msg.frame, param1=msg.param1, param2=msg.param2,
                       param3=msg.param3, param4=msg.param4, lat=msg.x / 1e7, lon=msg.y / 1e7, alt=msg.z,
                       autocontinue=msg.autocontinue)


# ----------------------------------------------------------------------------- link
@dataclass
class SeqStats:
    received: int = 0
    lost: int = 0
    last_seq: int | None = None

    def update(self, seq: int):
        if self.last_seq is not None:
            gap = (seq - self.last_seq - 1) % 256
            if gap < 128:          # ignore wild jumps (reconnects)
                self.lost += gap
        self.last_seq = seq
        self.received += 1

    @property
    def loss_rate(self) -> float:
        tot = self.received + self.lost
        return self.lost / tot if tot else 0.0


@dataclass
class Latest:
    msg: object
    t: float                  # time.perf_counter() at receipt


class LinkError(RuntimeError):
    pass


class Link:
    """A MAVLink connection with a background receiver.

    role="ro": never sends anything except what the caller explicitly sends (core must not send at all).
    role="rw": sends a 1 Hz HEARTBEAT as GCS (signed if key given) -> keeps the GCS failsafe satisfied.
    """

    def __init__(self, url: str, sysid: int, compid: int = GCS_COMPID, key: bytes | None = None,
                 role: str = "ro", name: str = "", heartbeat_hz: float = 1.0, inbox: int = 4000):
        self.url, self.role, self.name = url, role, name or url
        self.m = mavutil.mavlink_connection(url, source_system=sysid, source_component=compid,
                                            autoreconnect=True, dialect="ardupilotmega")
        self.signed = key is not None
        if key is not None:
            self.m.setup_signing(key, sign_outgoing=True)
        self.latest: dict[str, Latest] = {}
        self.seq: dict[tuple, SeqStats] = {}
        self.target_system: int | None = None
        self.target_component: int = 1
        self._inbox: deque = deque(maxlen=inbox)
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._send_lock = threading.Lock()
        self.heartbeats_sent = 0
        self._rx = threading.Thread(target=self._rx_loop, name=f"mav-rx-{self.name}", daemon=True)
        self._rx.start()
        self._hb = None
        if role == "rw" and heartbeat_hz > 0:
            self._hb_period = 1.0 / heartbeat_hz
            self._hb_enabled = threading.Event()
            self._hb_enabled.set()
            self._hb = threading.Thread(target=self._hb_loop, name=f"mav-hb-{self.name}", daemon=True)
            self._hb.start()

    # -- lifecycle
    def close(self):
        self._stop.set()
        try:
            self.m.close()
        except Exception:
            pass

    def pause_heartbeat(self, paused: bool = True):
        """Test hook: simulate governor link loss without closing the socket."""
        if self._hb is not None:
            (self._hb_enabled.clear if paused else self._hb_enabled.set)()

    # -- rx
    def _rx_loop(self):
        while not self._stop.is_set():
            try:
                msg = self.m.recv_match(blocking=True, timeout=0.5)
            except Exception:
                time.sleep(0.2)
                continue
            if msg is None:
                continue
            typ = msg.get_type()
            if typ == "BAD_DATA":
                continue
            t = time.perf_counter()
            src = (msg.get_srcSystem(), msg.get_srcComponent())
            self.seq.setdefault(src, SeqStats()).update(msg.get_seq())
            if typ == "HEARTBEAT" and msg.autopilot != mavlink.MAV_AUTOPILOT_INVALID and src[1] == 1:
                self.target_system = src[0]
            with self._cv:
                self.latest[typ] = Latest(msg, t)
                self._inbox.append((t, msg))
                self._cv.notify_all()

    def _hb_loop(self):
        while not self._stop.is_set():
            if self._hb_enabled.is_set():
                try:
                    with self._send_lock:
                        self.m.mav.heartbeat_send(mavlink.MAV_TYPE_GCS, mavlink.MAV_AUTOPILOT_INVALID, 0, 0,
                                                  mavlink.MAV_STATE_ACTIVE)
                    self.heartbeats_sent += 1
                except Exception:
                    pass
            self._stop.wait(self._hb_period)

    # -- queries
    def wait_heartbeat(self, timeout=30.0):
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            if self.target_system is not None:
                return self.latest["HEARTBEAT"].msg
            time.sleep(0.05)
        raise LinkError(f"{self.name}: no autopilot heartbeat within {timeout}s")

    def age(self, typ: str) -> float:
        l = self.latest.get(typ)
        return float("inf") if l is None else time.perf_counter() - l.t

    def get(self, typ: str):
        l = self.latest.get(typ)
        return None if l is None else l.msg

    def autopilot_loss_rate(self) -> float:
        st = self.seq.get((self.target_system, 1)) if self.target_system else None
        return st.loss_rate if st else 1.0

    def wait(self, types: str | Iterable[str], cond: Callable = lambda m: True, timeout: float = 5.0,
             since: float | None = None):
        """Wait for a message of `types` received at/after `since` (monotonic) satisfying cond."""
        types = {types} if isinstance(types, str) else set(types)
        start = time.perf_counter() if since is None else since
        deadline = time.perf_counter() + timeout
        seen = 0
        with self._cv:
            while True:
                items = list(self._inbox)
                for t, msg in items:
                    if t >= start and msg.get_type() in types and cond(msg):
                        return msg
                seen = len(items)
                rem = deadline - time.perf_counter()
                if rem <= 0:
                    return None
                self._cv.wait(min(rem, 0.25))

    # -- tx
    @property
    def ts(self) -> int:
        if self.target_system is None:
            raise LinkError("no target yet")
        return self.target_system

    def send(self, fn_name: str, *args):
        with self._send_lock:
            getattr(self.m.mav, fn_name)(*args)

    def command_long(self, cmd: int, p1=0, p2=0, p3=0, p4=0, p5=0, p6=0, p7=0, timeout=3.0, retries=2):
        """Send COMMAND_LONG and return the COMMAND_ACK result (or None on timeout)."""
        for attempt in range(retries + 1):
            t = time.perf_counter()
            self.send("command_long_send", self.ts, self.target_component, cmd, attempt, p1, p2, p3, p4, p5, p6, p7)
            ack = self.wait("COMMAND_ACK", lambda m: m.command == cmd, timeout=timeout, since=t)
            if ack is not None:
                return ack.result
        return None

    def set_mode(self, mode: str, timeout=5.0) -> bool:
        mapping = self.m.mode_mapping() or mavutil.mode_mapping_apm
        if mode not in mapping:
            raise ValueError(f"unknown mode {mode}")
        num = mapping[mode]
        r = self.command_long(mavlink.MAV_CMD_DO_SET_MODE, mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, num)
        t = time.perf_counter()
        hb = self.wait("HEARTBEAT", lambda m: m.custom_mode == num and m.get_srcComponent() == 1, timeout=timeout,
                       since=t - 0.5)
        return r == mavlink.MAV_RESULT_ACCEPTED and hb is not None

    def flightmode(self) -> str:
        hb = self.get("HEARTBEAT")
        if hb is None:
            return "?"
        inv = {v: k for k, v in (self.m.mode_mapping() or {}).items()}
        return inv.get(hb.custom_mode, str(hb.custom_mode))

    def set_current(self, seq: int, timeout=4.0) -> bool:
        """Jump the mission to `seq` (MAV_CMD_DO_SET_MISSION_CURRENT, fallback MISSION_SET_CURRENT)."""
        t = time.perf_counter()
        r = self.command_long(mavlink.MAV_CMD_DO_SET_MISSION_CURRENT, seq, 0)
        if r != mavlink.MAV_RESULT_ACCEPTED:
            self.send("mission_set_current_send", self.ts, self.target_component, seq)
        return self.wait("MISSION_CURRENT", lambda m: m.seq == seq, timeout=timeout, since=t) is not None

    def get_param(self, name: str, timeout=3.0):
        t = time.perf_counter()
        self.send("param_request_read_send", self.ts, self.target_component, name.encode(), -1)
        msg = self.wait("PARAM_VALUE", lambda m: m.param_id == name, timeout=timeout, since=t)
        return None if msg is None else msg.param_value

    # -- mission protocol
    def upload_mission(self, items: list[MissionItem], home: MissionItem | None = None, timeout=4.0,
                       mission_type: int = 0) -> None:
        """Upload `items` as seq 1..N (seq 0 = home placeholder). Raises LinkError on failure."""
        allitems = [home or MissionItem(mavlink.MAV_CMD_NAV_WAYPOINT, frame=mavlink.MAV_FRAME_GLOBAL_INT)] + list(items)
        n = len(allitems)
        t = time.perf_counter()
        self.send("mission_count_send", self.ts, self.target_component, n, mission_type)
        sent = set()
        deadline = time.perf_counter() + timeout + 0.25 * n
        while time.perf_counter() < deadline:
            msg = self.wait(["MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK"], timeout=timeout, since=t)
            if msg is None:
                raise LinkError(f"mission upload stalled after {len(sent)}/{n} items")
            t = time.perf_counter()
            if msg.get_type() == "MISSION_ACK":
                if msg.type == mavlink.MAV_MISSION_ACCEPTED and len(sent) >= n:
                    return
                # ArduPilot NACKs a duplicate/late item with INVALID_SEQUENCE but keeps the transfer going
                if msg.type not in (mavlink.MAV_MISSION_ACCEPTED, mavlink.MAV_MISSION_INVALID_SEQUENCE):
                    raise LinkError(f"mission rejected: {mavlink.enums['MAV_MISSION_RESULT'][msg.type].name}")
                continue
            s = msg.seq
            it = allitems[s]
            self.send("mission_item_int_send", self.ts, self.target_component, s, it.frame, it.command,
                      0, it.autocontinue, it.param1, it.param2, it.param3, it.param4, it.x, it.y, it.alt,
                      mission_type)
            sent.add(s)
        raise LinkError("mission upload timed out")

    def download_mission(self, timeout=4.0, mission_type: int = 0, skip_home: bool | None = None) -> list[MissionItem]:
        """Return items as stored on the autopilot: seq 1..N-1 for missions (seq 0 = home), all items for fences."""
        skip_home = (mission_type == 0) if skip_home is None else skip_home
        cnt = None
        for _ in range(3):        # one lost reply on the radio/Pi link must not fail a read-back (seen on the Pi 3, 05:17)
            t = time.perf_counter()
            self.send("mission_request_list_send", self.ts, self.target_component, mission_type)
            cnt = self.wait("MISSION_COUNT", timeout=timeout, since=t)
            if cnt is not None:
                break
        if cnt is None:
            raise LinkError("no MISSION_COUNT")
        items = []
        for s in range(cnt.count):
            got = None
            for _ in range(3):
                t = time.perf_counter()
                self.send("mission_request_int_send", self.ts, self.target_component, s, mission_type)
                got = self.wait("MISSION_ITEM_INT", lambda m, s=s: m.seq == s, timeout=timeout, since=t)
                if got is not None:
                    break
            if got is None:
                raise LinkError(f"no MISSION_ITEM_INT {s}")
            items.append(item_from_msg(got))
        self.send("mission_ack_send", self.ts, self.target_component, mavlink.MAV_MISSION_ACCEPTED, mission_type)
        return items[1:] if skip_home else items

    def upload_fence_polygon(self, polygon_latlon: list[tuple[float, float]]):
        """Inclusion polygon via the mission protocol (MAV_MISSION_TYPE_FENCE)."""
        n = len(polygon_latlon)
        items = [MissionItem(mavlink.MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION, frame=mavlink.MAV_FRAME_GLOBAL,
                             param1=n, lat=lat, lon=lon) for lat, lon in polygon_latlon]
        # fence uploads have no home item: send seq 0..n-1 directly
        t = time.perf_counter()
        self.send("mission_count_send", self.ts, self.target_component, n, mavlink.MAV_MISSION_TYPE_FENCE)
        sent = 0
        while True:
            msg = self.wait(["MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK"], timeout=4.0, since=t)
            if msg is None:
                raise LinkError("fence upload stalled")
            t = time.perf_counter()
            if msg.get_type() == "MISSION_ACK":
                if msg.type == mavlink.MAV_MISSION_ACCEPTED and sent >= n:
                    return
                if msg.type not in (mavlink.MAV_MISSION_ACCEPTED, mavlink.MAV_MISSION_INVALID_SEQUENCE):
                    raise LinkError(f"fence rejected {msg.type}")
                continue
            it = items[msg.seq]
            self.send("mission_item_int_send", self.ts, self.target_component, msg.seq, it.frame, it.command, 0, 1,
                      it.param1, 0, 0, 0, it.x, it.y, 0, mavlink.MAV_MISSION_TYPE_FENCE)
            sent += 1


def install_signing_key(link: Link, key: bytes):
    """Send SETUP_SIGNING to the autopilot. Do this over USB (real FC) or an unsigned SITL port at setup."""
    link.send("setup_signing_send", link.ts, link.target_component, list(key), int((time.time() - 1420070400) * 1e5))
