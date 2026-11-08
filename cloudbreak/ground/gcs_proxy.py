"""Signing proxy: run Mission Planner (or QGroundControl, MAVProxy, the repo scripts) on the REAL, signed FC.

    .venv\\Scripts\\python scripts\\gcs_proxy.py                       # FC on this laptop's USB (finds the ArduPilot port)
    .venv\\Scripts\\python scripts\\gcs_proxy.py --fc COM5
    .venv\\Scripts\\python scripts\\gcs_proxy.py --fc tcp:129.161.144.214:14560   # through the Pi's signed uplink
    .venv\\Scripts\\python scripts\\gcs_proxy.py --read-only           # watch only: nothing that changes the FC is sent

Then:  Mission Planner -> connection type UDP, Connect, port 14550 (QGroundControl auto-connects on UDP 14550).
       Repo scripts    -> --port tcp:127.0.0.1:5770   (e.g. fc_setup_usb.py, fc_bench.py)

Why: since the key went in (fc_setup_usb.py), the FC signs every frame it sends, USB included. A ground station
without the key throws all of it away, and Mission Planner's signing dialog derives its key from a passphrase,
so it can't hold our random 32-byte key. The proxy holds the key (C:\\cb-data\\keys\\mavlink_real.key) instead:
  FC -> ground stations: each frame's signature is checked against the key; frames with a bad signature, no signature
      or a replayed timestamp are dropped. Good frames go on with the signature removed.
  ground stations -> FC: each frame is signed again with the key (proxy timestamp, link id 7), so the same proxy
      works over USB and through the Pi. SETUP_SIGNING is never forwarded: no ground station can change or clear
      the key. Frames claiming the FC's own sysid are dropped.
  Nothing is sent to the FC until one of its frames has verified with the real key, so the proxy can't be
      pointed at SITL (different key) by mistake.
Listens on 127.0.0.1 only. Every parameter write, command, mode change and mission/fence upload from a ground
station is logged to C:\\cb-data\\proxy\\proxy_<time>.log.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MAVLINK20", "1")
from pymavlink.dialects.v20 import all as mavall  # noqa: E402

MAGIC_V2, MAGIC_V1 = 0xFD, 0xFE
IFLAG_SIGNED = 0x01
SIG_LEN = 13
EPOCH_2015 = 1420070400
PROXY_LINK_ID = 7                # the governor signs on link 0; separate (sysid, compid, link) streams on the FC
REANCHOR_S = 2.0                 # a lower FC timestamp sequence (FC reboot reloads an older saved stamp) is accepted
                                 # after it has run consistently for this long
FC_SYSID = 42
DEFAULT_UDP_GCS = ("127.0.0.1", 14550)
DEFAULT_TCP = ("127.0.0.1", 5770)
ARDUPILOT_USB = (0x1209, 0x5741)

def _ids(*names: str) -> set[int]:
    return {getattr(mavall, f"MAVLINK_MSG_ID_{n}") for n in names}


def _cmds(*names: str) -> set[int]:
    return {getattr(mavall, f"MAV_CMD_{n}") for n in names}


MSG_HEARTBEAT, MSG_SET_MODE, MSG_PARAM_SET = mavall.MAVLINK_MSG_ID_HEARTBEAT, mavall.MAVLINK_MSG_ID_SET_MODE, mavall.MAVLINK_MSG_ID_PARAM_SET
MSG_COMMAND_INT, MSG_COMMAND_LONG = mavall.MAVLINK_MSG_ID_COMMAND_INT, mavall.MAVLINK_MSG_ID_COMMAND_LONG
MSG_SETUP_SIGNING, MSG_FTP = mavall.MAVLINK_MSG_ID_SETUP_SIGNING, mavall.MAVLINK_MSG_ID_FILE_TRANSFER_PROTOCOL
COMMAND_OFFSET = {MSG_COMMAND_LONG: 28, MSG_COMMAND_INT: 32}    # byte offset of the uint16 command in the payload
# --read-only: what a ground station may still send (requests and protocol acks; nothing that changes the FC)
READ_ONLY_OK = _ids("HEARTBEAT", "SYSTEM_TIME", "PING", "TIMESYNC", "PARAM_REQUEST_READ", "PARAM_REQUEST_LIST",
                    "REQUEST_DATA_STREAM", "MISSION_REQUEST_LIST", "MISSION_REQUEST_PARTIAL_LIST", "MISSION_REQUEST",
                    "MISSION_REQUEST_INT", "MISSION_ACK", "LOG_REQUEST_LIST", "LOG_REQUEST_DATA", "LOG_REQUEST_END",
                    "AUTOPILOT_VERSION_REQUEST")
READ_ONLY_COMMANDS = _cmds("SET_MESSAGE_INTERVAL", "GET_MESSAGE_INTERVAL", "REQUEST_MESSAGE",
                           "REQUEST_PROTOCOL_VERSION", "REQUEST_AUTOPILOT_CAPABILITIES", "DO_SEND_BANNER")
FTP_READ_OPCODES = {0, 1, 2, 3, 4, 5, 14, 15}                    # none/terminate/reset/list/open RO/read/crc/burst
# logged with their content (RC overrides / MANUAL_CONTROL are not: a joystick sends them many times a second)
LOGGED = _ids("SET_MODE", "PARAM_SET", "COMMAND_INT", "COMMAND_LONG", "MISSION_COUNT", "MISSION_CLEAR_ALL",
              "MISSION_SET_CURRENT", "MISSION_WRITE_PARTIAL_LIST", "SETUP_SIGNING", "LOG_ERASE", "SERIAL_CONTROL",
              "SET_POSITION_TARGET_GLOBAL_INT", "SET_POSITION_TARGET_LOCAL_NED", "SET_ATTITUDE_TARGET")


def crc_extra(msgid: int) -> int | None:
    cls = mavall.mavlink_map.get(msgid)
    return None if cls is None else cls.crc_extra


def x25(data: bytes) -> int:
    return mavall.x25crc(data).crc


def signing_timestamp(now: float | None = None) -> int:
    """MAVLink2 signing time: 10 us units since 2015-01-01 UTC."""
    return int(((time.time() if now is None else now) - EPOCH_2015) * 1e5)


@dataclass
class Frame:
    raw: bytes                 # the complete frame as received
    version: int               # 1 or 2
    msgid: int
    sysid: int
    compid: int
    seq: int
    payload: bytes
    signed: bool

    @property
    def header_v2(self) -> bytes:
        return self.raw[:10]

    @property
    def link_id(self) -> int:
        return self.raw[-SIG_LEN]

    @property
    def sig_timestamp(self) -> int:
        return int.from_bytes(self.raw[-12:-6], "little")


class FrameParser:
    """Incremental MAVLink 1/2 framer. Checks the CRC when the message is known; a signed v2 frame of an
    unknown message is kept (its signature is checked by the caller); anything else that doesn't check out is
    treated as noise and the parser resyncs one byte later."""

    def __init__(self):
        self.buf = bytearray()
        self.noise = 0
        self.unknown = 0

    def feed(self, data: bytes) -> list[Frame]:
        self.buf += data
        out: list[Frame] = []
        b = self.buf
        i = 0
        while True:
            while i < len(b) and b[i] not in (MAGIC_V1, MAGIC_V2):
                i += 1
                self.noise += 1
            if i >= len(b):
                break
            if b[i] == MAGIC_V2:
                if len(b) - i < 10:
                    break
                ln, inc = b[i + 1], b[i + 2]
                total = 10 + ln + 2 + (SIG_LEN if inc & IFLAG_SIGNED else 0)
                if len(b) - i < total:
                    break
                raw = bytes(b[i:i + total])
                msgid = raw[7] | (raw[8] << 8) | (raw[9] << 16)
                extra = crc_extra(msgid)
                crc = raw[10 + ln] | (raw[11 + ln] << 8)
                if extra is None:
                    ok = bool(inc & IFLAG_SIGNED)
                    if ok:
                        self.unknown += 1
                else:
                    ok = x25(raw[1:10 + ln] + bytes([extra])) == crc
                if not ok or (inc & ~IFLAG_SIGNED):
                    i += 1
                    self.noise += 1
                    continue
                out.append(Frame(raw, 2, msgid, raw[5], raw[6], raw[4], raw[10:10 + ln], bool(inc & IFLAG_SIGNED)))
                i += total
            else:
                if len(b) - i < 6:
                    break
                ln = b[i + 1]
                total = 6 + ln + 2
                if len(b) - i < total:
                    break
                raw = bytes(b[i:i + total])
                msgid = raw[5]
                extra = crc_extra(msgid)
                crc = raw[6 + ln] | (raw[7 + ln] << 8)
                if extra is None or x25(raw[1:6 + ln] + bytes([extra])) != crc:
                    i += 1
                    self.noise += 1
                    continue
                out.append(Frame(raw, 1, msgid, raw[3], raw[4], raw[2], raw[6:6 + ln], False))
                i += total
        del b[:i]
        if len(b) > 4096:          # never let garbage grow without bound
            self.noise += len(b) - 280
            del b[:-280]
        return out


def verify_signature(frame: Frame, key: bytes) -> bool:
    if frame.version != 2 or not frame.signed:
        return False
    return hashlib.sha256(key + frame.raw[:-6]).digest()[:6] == frame.raw[-6:]


def strip_signature(frame: Frame) -> bytes | None:
    """The same v2 frame without its signature (incompat flag cleared, CRC recomputed). None if unknown msgid."""
    if frame.version != 2:
        return frame.raw
    if not frame.signed:
        return frame.raw
    extra = crc_extra(frame.msgid)
    if extra is None:
        return None
    hdr = bytearray(frame.raw[:10])
    hdr[2] &= ~IFLAG_SIGNED
    body = bytes(hdr) + frame.payload
    return body + struct.pack("<H", x25(body[1:] + bytes([extra])))


def sign_frame(frame: Frame, key: bytes, timestamp: int, link_id: int = PROXY_LINK_ID) -> bytes:
    """Re-encode any v1/v2 frame as a signed MAVLink2 frame with the same sysid/compid/seq/payload."""
    extra = crc_extra(frame.msgid)
    if extra is None:
        raise ValueError(f"unknown message id {frame.msgid}")
    hdr = bytes([MAGIC_V2, len(frame.payload), IFLAG_SIGNED, 0, frame.seq, frame.sysid, frame.compid,
                 frame.msgid & 0xFF, (frame.msgid >> 8) & 0xFF, (frame.msgid >> 16) & 0xFF])
    body = hdr + frame.payload
    body += struct.pack("<H", x25(body[1:] + bytes([extra])))
    body += bytes([link_id]) + timestamp.to_bytes(6, "little")
    return body + hashlib.sha256(key + body).digest()[:6]


class Signer:
    """Monotonic signing clock shared by every ground station going through the proxy."""

    def __init__(self, key: bytes, link_id: int = PROXY_LINK_ID):
        self.key, self.link_id = key, link_id
        self.last = 0
        self.lock = threading.Lock()

    def sign(self, frame: Frame) -> bytes:
        with self.lock:
            self.last = max(signing_timestamp(), self.last + 1)
            ts = self.last
        return sign_frame(frame, self.key, ts, self.link_id)


class Downlink:
    """Signature + replay checks for frames from the FC."""

    def __init__(self, key: bytes, reanchor_s: float = REANCHOR_S):
        self.key, self.reanchor_s = key, reanchor_s
        self.last: dict[tuple, int] = {}
        self.behind: dict[tuple, tuple[float, int]] = {}
        self.counts = dict(ok=0, bad_sig=0, unsigned=0, replay=0, reanchored=0, unknown_msg=0)
        self.verified_once = False
        self.notes: list[str] = []

    def accept(self, frame: Frame, now: float | None = None) -> bytes | None:
        now = time.monotonic() if now is None else now
        if not frame.signed:
            self.counts["unsigned"] += 1
            return None
        if not verify_signature(frame, self.key):
            self.counts["bad_sig"] += 1
            return None
        stream = (frame.sysid, frame.compid, frame.link_id)
        ts = frame.sig_timestamp
        last = self.last.get(stream)
        if last is not None and ts <= last:
            first_t, prev = self.behind.get(stream, (now, -1))
            if ts <= prev:
                first_t = now                      # not even increasing among itself: start over
            self.behind[stream] = (first_t, ts)
            if now - first_t < self.reanchor_s:
                self.counts["replay"] += 1
                return None
            self.counts["reanchored"] += 1
            self.notes.append(f"FC signing clock for {stream} went back and stayed back {self.reanchor_s:.0f} s "
                              f"(FC reboot?): re-anchored")
        self.behind.pop(stream, None)
        self.last[stream] = ts
        out = strip_signature(frame)
        if out is None:
            self.counts["unknown_msg"] += 1
            return None
        self.counts["ok"] += 1
        self.verified_once = True
        return out


class UplinkPolicy:
    """What a ground station's frame may do on its way to the FC. Returns (forward?, reason, log line)."""

    def __init__(self, read_only: bool = False, fc_sysid: int = FC_SYSID):
        self.read_only, self.fc_sysid = read_only, fc_sysid
        self._dec = mavall.MAVLink(None)

    def describe(self, frame: Frame) -> str | None:
        if frame.msgid not in LOGGED and frame.msgid != MSG_FTP:
            return None
        try:
            unsigned = strip_signature(frame) if frame.signed else frame.raw
            m = self._dec.decode(bytearray(unsigned))
        except Exception as e:  # pragma: no cover - logged, never forwarded blindly
            return f"msgid {frame.msgid} (undecodable: {e})"
        t = m.get_type()
        if t == "PARAM_SET":
            return f"PARAM_SET {m.param_id} = {m.param_value:g}"
        if t in ("COMMAND_LONG", "COMMAND_INT"):
            cmd = mavall.enums["MAV_CMD"].get(m.command)
            name = cmd.name if cmd else str(m.command)
            ps = [m.param1, m.param2, m.param3, m.param4] + ([m.param5, m.param6, m.param7] if t == "COMMAND_LONG"
                                                            else [m.x, m.y, m.z])
            return f"{t} {name} " + " ".join(f"{p:g}" for p in ps)
        if t == "SET_MODE":
            return f"SET_MODE base {m.base_mode} custom {m.custom_mode}"
        if t == "MISSION_COUNT":
            return f"MISSION_COUNT {m.count} (type {getattr(m, 'mission_type', 0)})"
        if t == "FILE_TRANSFER_PROTOCOL":
            op = m.payload[3] if len(m.payload) > 3 else -1
            return None if op in FTP_READ_OPCODES else f"FTP write opcode {op}"
        return t

    def check(self, frame: Frame) -> tuple[bool, str]:
        if frame.sysid == self.fc_sysid:
            return False, "claims the FC's sysid"
        if frame.msgid == MSG_SETUP_SIGNING:
            return False, "SETUP_SIGNING is never forwarded (use fc_setup_usb.py)"
        if crc_extra(frame.msgid) is None:
            return False, f"unknown message id {frame.msgid}"
        if self.read_only:
            if frame.msgid in COMMAND_OFFSET:
                cmd = struct.unpack_from("<H", frame.payload.ljust(40, b"\0"), COMMAND_OFFSET[frame.msgid])[0]
                if cmd not in READ_ONLY_COMMANDS:
                    return False, f"read-only: command {cmd}"
                return True, ""
            if frame.msgid == MSG_FTP:
                op = frame.payload[6] if len(frame.payload) > 6 else 0
                return (op in FTP_READ_OPCODES), f"read-only: FTP opcode {op}"
            if frame.msgid not in READ_ONLY_OK:
                return False, f"read-only: msgid {frame.msgid}"
        return True, ""


def find_fc_port() -> str | None:
    from serial.tools import list_ports

    for p in list_ports.comports():
        if (p.vid, p.pid) == ARDUPILOT_USB or "ArduPilot" in (p.description or ""):
            return p.device
    return None


class FcTransport:
    """USB serial (pyserial) or TCP to the Pi bridge, reconnecting on its own (the FC re-enumerates on reboot)."""

    def __init__(self, url: str):
        self.url = url
        self.kind = "tcp" if url.startswith("tcp:") else "serial"
        self.h = None
        self.lock = threading.Lock()
        self.connected = threading.Event()

    def open(self):
        if self.kind == "tcp":
            _, host, port = self.url.split(":")
            s = socket.create_connection((host, int(port)), timeout=5)
            s.settimeout(0.5)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.h = s
        else:
            import serial

            port = self.url[len("serial:"):] if self.url.startswith("serial:") else self.url
            self.h = serial.Serial(port, 115200, timeout=0.2, write_timeout=1)
        self.connected.set()

    def close(self):
        self.connected.clear()
        try:
            if self.h is not None:
                self.h.close()
        except Exception:
            pass
        self.h = None

    def read(self) -> bytes:
        if self.kind == "tcp":
            try:
                d = self.h.recv(4096)
            except socket.timeout:
                return b""
            if not d:
                raise ConnectionError("Pi closed the connection")
            return d
        return self.h.read(self.h.in_waiting or 1)

    def write(self, data: bytes):
        with self.lock:
            if self.h is None:
                raise ConnectionError("FC not connected")
            if self.kind == "tcp":
                self.h.sendall(data)
            else:
                self.h.write(data)


class Proxy:
    def __init__(self, fc_url: str, key: bytes, udp_gcs=DEFAULT_UDP_GCS, tcp_listen=DEFAULT_TCP,
                 read_only: bool = False, log_path: Path | None = None, quiet: bool = False):
        self.fc = FcTransport(fc_url)
        self.down = Downlink(key)
        self.signer = Signer(key)
        self.policy = UplinkPolicy(read_only)
        self.udp_gcs, self.tcp_listen = udp_gcs, tcp_listen
        self.read_only, self.quiet = read_only, quiet
        self.stop = threading.Event()
        self.clients: dict[str, object] = {}       # name -> socket (tcp) ; udp handled separately
        self.clients_lock = threading.Lock()
        self.up = dict(forwarded=0, refused=0, before_verified=0, fc_write_err=0)
        self.refusals: dict[str, int] = {}
        self.last_hb = None
        self.log_path = log_path
        self._log_lock = threading.Lock()
        self.udp = None
        self._last_open_err = None
        self._udp_peers: set = set()
        self._warned_unverified = False

    # -- logging
    def log(self, line: str, echo: bool = True):
        stamp = time.strftime("%H:%M:%S")
        if echo and not self.quiet:
            print(f"[{stamp}] {line}", flush=True)
        if self.log_path is not None:
            with self._log_lock, open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d')} {stamp} {line}\n")

    # -- downlink
    def _broadcast(self, data: bytes):
        if self.udp is not None and self.udp_gcs:
            try:
                self.udp.sendto(data, self.udp_gcs)
            except OSError:
                pass
        with self.clients_lock:
            items = list(self.clients.items())
        for name, s in items:
            try:
                s.sendall(data)
            except OSError:
                self._drop_client(name)

    def _fc_loop(self):
        parser = FrameParser()
        while not self.stop.is_set():
            if not self.fc.connected.is_set():
                try:
                    self.fc.open()
                    parser = FrameParser()
                    self.log(f"FC connected on {self.fc.url}")
                except Exception as e:
                    self.stop.wait(1.0)
                    if self._last_open_err != str(e):
                        self._last_open_err = str(e)
                        self.log(f"waiting for the FC on {self.fc.url}: {e}")
                    continue
            try:
                data = self.fc.read()
            except Exception as e:
                self.log(f"FC link lost ({e}); reconnecting")
                self.fc.close()
                continue
            if not data:
                continue
            for fr in parser.feed(data):
                out = self.down.accept(fr)
                if self.down.notes:
                    for n in self.down.notes:
                        self.log(n)
                    self.down.notes.clear()
                if out is None:
                    continue
                if fr.msgid == MSG_HEARTBEAT and fr.compid == 1:
                    if self.last_hb is None:
                        self.log(f"FC frames verify with the real key (sysid {fr.sysid}); ground stations may now "
                                 f"{'watch' if self.read_only else 'operate'}")
                    self.last_hb = (time.monotonic(), fr.payload)
                self._broadcast(out)

    # -- uplink
    def _from_gcs(self, name: str, frames: list[Frame]):
        for fr in frames:
            if not self.down.verified_once:
                self.up["before_verified"] += 1
                if not self._warned_unverified:
                    self._warned_unverified = True
                    c = self.down.counts
                    self.log(f"holding {name}'s frames: no FC frame has verified with the real key yet "
                             f"(bad signature {c['bad_sig']}, unsigned {c['unsigned']})")
                continue
            ok, why = self.policy.check(fr)
            desc = self.policy.describe(fr)
            if not ok:
                self.up["refused"] += 1
                key = f"{name}: {why}"
                n = self.refusals.get(key, 0)
                self.refusals[key] = n + 1
                if n == 0:
                    self.log(f"REFUSED from {name} (sysid {fr.sysid}): {why}" + (f" [{desc}]" if desc else ""))
                continue
            try:
                self.fc.write(self.signer.sign(fr))
                self.up["forwarded"] += 1
            except Exception as e:
                self.up["fc_write_err"] += 1
                self.log(f"could not send to the FC ({e}); dropped {desc or fr.msgid}", echo=desc is not None)
                continue
            if desc:
                self.log(f"{name} (sysid {fr.sysid}): {desc}")

    def _udp_loop(self):
        parser = FrameParser()
        while not self.stop.is_set():
            try:
                data, addr = self.udp.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                continue
            if addr not in self._udp_peers:
                self._udp_peers.add(addr)
                self.log(f"UDP ground station talking from {addr[0]}:{addr[1]}")
            self._from_gcs("udp", parser.feed(data))

    def _drop_client(self, name: str):
        with self.clients_lock:
            s = self.clients.pop(name, None)
        if s is not None:
            try:
                s.close()
            except OSError:
                pass
            self.log(f"{name} disconnected")

    def _tcp_client(self, s: socket.socket, name: str):
        parser = FrameParser()
        s.settimeout(0.5)
        while not self.stop.is_set():
            try:
                d = s.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not d:
                break
            self._from_gcs(name, parser.feed(d))
        self._drop_client(name)

    def _tcp_accept(self, srv: socket.socket):
        while not self.stop.is_set():
            try:
                s, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            name = f"tcp {addr[0]}:{addr[1]}"
            with self.clients_lock:
                self.clients[name] = s
            self.log(f"{name} connected")
            threading.Thread(target=self._tcp_client, args=(s, name), daemon=True).start()

    def status_line(self) -> str:
        c = self.down.counts
        hb = "no FC heartbeat yet"
        if self.last_hb is not None:
            age = time.monotonic() - self.last_hb[0]
            custom_mode, typ, ap, base_mode = struct.unpack_from("<IBBB", self.last_hb[1].ljust(9, b"\0"))
            hb = f"FC hb {age:.1f}s ago, {'ARMED' if base_mode & 128 else 'disarmed'}, mode {custom_mode}"
        with self.clients_lock:
            n = len(self.clients)
        return (f"{hb} | down ok {c['ok']} badsig {c['bad_sig']} unsigned {c['unsigned']} replay {c['replay']} | "
                f"up fwd {self.up['forwarded']} refused {self.up['refused']} | tcp clients {n}")

    def start(self):
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.udp.settimeout(0.5)
        if hasattr(socket, "SIO_UDP_CONNRESET"):        # Windows: an absent GCS must not break recvfrom
            self.udp.ioctl(socket.SIO_UDP_CONNRESET, False)
        threading.Thread(target=self._udp_loop, daemon=True).start()
        if self.tcp_listen:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(self.tcp_listen)
            srv.listen(4)
            srv.settimeout(0.5)
            self._srv = srv
            threading.Thread(target=self._tcp_accept, args=(srv,), daemon=True).start()
        threading.Thread(target=self._fc_loop, daemon=True).start()

    def close(self):
        self.stop.set()
        self.fc.close()
        for s in [self.udp, getattr(self, "_srv", None)]:
            try:
                if s is not None:
                    s.close()
            except OSError:
                pass


def main(argv=None) -> int:
    from cloudbreak.common.config import data_dir
    from cloudbreak.common.mav import load_key

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fc", help="COMx (default: the ArduPilot USB port) or tcp:<pi>:14560 (the Pi's signed uplink)")
    ap.add_argument("--udp", default="127.0.0.1:14550", help="send to a ground station listening here (Mission Planner "
                                                            "/ QGC UDP); 'off' to disable")
    ap.add_argument("--tcp", default="127.0.0.1:5770", help="TCP port for repo scripts / MAVProxy; 'off' to disable")
    ap.add_argument("--read-only", action="store_true", help="forward only requests: nothing that changes the FC")
    ap.add_argument("--status-every", type=float, default=15.0)
    a = ap.parse_args(argv)

    fc = a.fc or find_fc_port()
    if fc is None:
        print("No ArduPilot USB port found. Plug the FC in, or pass --fc COMx / --fc tcp:<pi>:14560.")
        return 2
    if fc.startswith("tcp:127.0.0.1:576") or fc.startswith("tcp:localhost:576"):
        print("refusing: that looks like SITL (127.0.0.1:576x). The proxy is for the real FC only.")
        return 2

    def hostport(s: str):
        if s.lower() == "off":
            return None
        h, p = s.rsplit(":", 1)
        if h not in ("127.0.0.1", "localhost"):
            raise SystemExit("the proxy only listens/sends on 127.0.0.1 (never on the campus network)")
        return ("127.0.0.1", int(p))

    logdir = data_dir() / "proxy"
    logdir.mkdir(parents=True, exist_ok=True)
    log_path = logdir / f"proxy_{time.strftime('%Y%m%dT%H%M%S')}.log"
    p = Proxy(fc, load_key("real"), udp_gcs=hostport(a.udp), tcp_listen=hostport(a.tcp), read_only=a.read_only,
              log_path=log_path)
    p.start()
    p.log(f"signing proxy: FC {fc} | Mission Planner: UDP 14550 | scripts: tcp:127.0.0.1:{p.tcp_listen[1] if p.tcp_listen else '-'}"
          f"{' | READ-ONLY' if a.read_only else ''} | log {log_path}")
    try:
        while True:
            time.sleep(a.status_every)
            p.log(p.status_line(), echo=True)
    except KeyboardInterrupt:
        p.log("stopped (Ctrl+C)")
    finally:
        p.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
