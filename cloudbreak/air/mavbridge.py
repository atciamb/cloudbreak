"""Pi <-> flight-controller MAVLink bridge.

  FC (UART /dev/serial0 @115200, or tcp:host:port when emulating with SITL)
    -> raw tlog (Pi CLOCK_BOOTTIME us + packet)          [always, even with no ground link]
    -> UDP to every known ground host (:14551)             [telemetry downlink, loss tolerant]
    -> FcClockModel (FC boot time -> Pi boottime)          [geotag timing]
    -> /dev/shm/cloudbreak_pose.json (10 Hz)               [for capture.py]
  Governor (TCP :14560) -> UplinkFilter -> FC              [signed, allowlisted only]

Run: python -m cloudbreak.air.mavbridge --config /etc/cloudbreak/air.toml
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import threading
import time
from pathlib import Path

os.environ.setdefault("MAVLINK20", "1")
from pymavlink import mavutil  # noqa: E402

from cloudbreak.air.config import load_air_config  # noqa: E402
from cloudbreak.air.uplink_filter import UplinkFilter  # noqa: E402
from cloudbreak.common.timebase import FcClockModel, boottime_ns  # noqa: E402

mavlink = mavutil.mavlink

STREAMS_US = {  # message id -> interval (us). Ignored by the FC once signing is on (then MAVn_* params apply).
    31: 40_000,    # ATTITUDE_QUATERNION 25 Hz
    30: 50_000,    # ATTITUDE 20 Hz
    33: 100_000,   # GLOBAL_POSITION_INT 10 Hz
    24: 200_000,   # GPS_RAW_INT 5 Hz
    2: 1_000_000,  # SYSTEM_TIME
    168: 500_000,  # WIND
    74: 200_000,   # VFR_HUD
    1: 1_000_000,  # SYS_STATUS
    193: 1_000_000,  # EKF_STATUS_REPORT
    65: 250_000,   # RC_CHANNELS
    42: 1_000_000,  # MISSION_CURRENT
    242: 2_000_000,  # HOME_POSITION
    178: 500_000,  # AHRS2
}
TIME_BOOT_MS_MSGS = {"ATTITUDE", "ATTITUDE_QUATERNION", "GLOBAL_POSITION_INT", "SYSTEM_TIME", "AHRS2", "SCALED_PRESSURE"}


class Bridge:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        b = cfg["bridge"]
        self.session_dir = Path(cfg["session_dir"])
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.fc = mavutil.mavlink_connection(b["fc_url"], baud=b.get("fc_baud", 115200), source_system=b.get("sysid", 42),
                                             source_component=mavlink.MAV_COMP_ID_ONBOARD_COMPUTER, autoreconnect=True)
        self.fc_lock = threading.Lock()
        self.clock = FcClockModel()
        self.filter = UplinkFilter()
        self.ground = {(h, int(b.get("ground_udp_port", 14551))) for h in b.get("ground_hosts", [])}
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.tlog = open(self.session_dir / "telemetry.tlog", "ab", buffering=0)
        self.pose: dict = {}
        self.stats = dict(fc_msgs=0, fc_bytes=0, udp_sent=0, udp_err=0, uplink_conn=0, last_fc_ns=0, streams_ok=False)
        self.ts_pending: dict[int, int] = {}
        self.uplink_queues: dict = {}          # id(deque) -> deque; deques are unhashable, so not a set
        self._stop = threading.Event()
        self.shm = Path(b.get("pose_shm", "/dev/shm/cloudbreak_pose.json"))
        self.meta = dict(started_wall=time.time(), started_boot_ns=boottime_ns(), fc_url=b["fc_url"])
        (self.session_dir / "bridge_meta.json").write_text(json.dumps(self.meta))

    # ------------------------------------------------------------------ FC rx
    def fc_loop(self):
        last_req = 0.0
        while not self._stop.is_set():
            msg = self.fc.recv_match(blocking=True, timeout=0.5)
            now = time.monotonic()
            if now - last_req > (30 if self.stats["streams_ok"] else 3):
                self.request_streams()
                last_req = now
            if msg is None:
                continue
            typ = msg.get_type()
            if typ == "BAD_DATA":
                continue
            t = boottime_ns()
            raw = msg.get_msgbuf()
            self.tlog.write(struct.pack(">Q", t // 1000) + raw)
            self.stats["fc_msgs"] += 1
            self.stats["fc_bytes"] += len(raw)
            self.stats["last_fc_ns"] = t
            for addr in list(self.ground):
                try:
                    self.udp.sendto(raw, addr)
                    self.stats["udp_sent"] += 1
                except OSError:
                    self.stats["udp_err"] += 1
            for q in list(self.uplink_queues.values()):     # governor's TCP connection gets the downlink too
                q.append(raw)
            if msg.get_srcComponent() != 1:
                continue
            if typ in TIME_BOOT_MS_MSGS and hasattr(msg, "time_boot_ms"):
                self.clock.add(t, int(msg.time_boot_ms) * 1_000_000, 1_000_000)
            elif typ == "TIMESYNC":
                if msg.tc1 == 0:                       # FC-originated: ts1 = FC boot ns
                    self.clock.add(t, int(msg.ts1), 1)
                elif msg.ts1 in self.ts_pending:      # reply to our request (only works before signing)
                    self.clock.add_twoway(self.ts_pending.pop(msg.ts1), int(msg.tc1), t)
            self._update_pose(typ, msg, t)

    def _update_pose(self, typ, msg, t):
        p = self.pose
        if typ == "GLOBAL_POSITION_INT":
            p.update(lat=msg.lat / 1e7, lon=msg.lon / 1e7, alt_msl=msg.alt / 1000, rel_alt=msg.relative_alt / 1000,
                     vn=msg.vx / 100, ve=msg.vy / 100, vd=msg.vz / 100, hdg=msg.hdg / 100, pos_tb_ms=msg.time_boot_ms,
                     pos_rx_ns=t)
            self.stats["streams_ok"] = True
        elif typ == "ATTITUDE_QUATERNION":
            p.update(q=[msg.q1, msg.q2, msg.q3, msg.q4], att_tb_ms=msg.time_boot_ms, att_rx_ns=t)
        elif typ == "ATTITUDE":
            p.update(roll=msg.roll, pitch=msg.pitch, yaw=msg.yaw, att_tb_ms=msg.time_boot_ms, att_rx_ns=t)
        elif typ == "VFR_HUD":
            p.update(groundspeed=msg.groundspeed, throttle=msg.throttle)
        elif typ == "GPS_RAW_INT":
            p.update(fix=msg.fix_type, sats=msg.satellites_visible, hdop=msg.eph / 100)
        elif typ == "HEARTBEAT":
            p.update(base_mode=msg.base_mode, custom_mode=msg.custom_mode, armed=bool(msg.base_mode & 128))
        elif typ == "WIND":
            p.update(wind_dir=msg.direction, wind_spd=msg.speed)

    def request_streams(self):
        with self.fc_lock:
            for mid, us in STREAMS_US.items():
                try:
                    self.fc.mav.command_long_send(self.fc.target_system or 1, 1, mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                                                  mid, us, 0, 0, 0, 0, 0)
                except Exception:
                    pass
            ts1 = boottime_ns()
            self.ts_pending[ts1] = ts1
            if len(self.ts_pending) > 20:
                self.ts_pending.pop(next(iter(self.ts_pending)))
            try:
                self.fc.mav.timesync_send(0, ts1)
            except Exception:
                pass

    # ------------------------------------------------------------------ uplink (governor -> FC)
    def uplink_server(self):
        port = int(self.cfg["bridge"].get("uplink_port", 14560))
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", port))
        srv.listen(1)
        while not self._stop.is_set():
            conn, addr = srv.accept()
            self.stats["uplink_conn"] += 1
            self.ground.add((addr[0], int(self.cfg["bridge"].get("ground_udp_port", 14551))))
            threading.Thread(target=self._uplink_client, args=(conn, addr), daemon=True).start()

    def _uplink_client(self, conn, addr):
        from collections import deque

        parser = mavlink.MAVLink(None)
        parser.robust_parsing = True
        conn.settimeout(1.0)
        q: deque = deque(maxlen=400)            # bounded: a stalled Wi-Fi link drops old telemetry, never blocks
        self.uplink_queues[id(q)] = q
        alive = threading.Event()
        alive.set()

        def sender():
            while alive.is_set():
                if not q:
                    time.sleep(0.01)
                    continue
                buf = b"".join(q.popleft() for _ in range(min(len(q), 50)))
                try:
                    conn.sendall(buf)
                except OSError:
                    alive.clear()

        threading.Thread(target=sender, daemon=True).start()
        try:
            self._uplink_rx(conn, parser, alive)
        finally:
            alive.clear()
            self.uplink_queues.pop(id(q), None)
            conn.close()

    def _uplink_rx(self, conn, parser, alive):
        while not self._stop.is_set() and alive.is_set():
            try:
                data = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            try:
                msgs = parser.parse_buffer(data) or []
            except Exception:
                continue
            for m in msgs:
                if m.get_type() == "BAD_DATA":
                    continue
                v = self.filter.check(m)
                if v.forward:
                    with self.fc_lock:
                        self.fc.write(m.get_msgbuf())

    # ------------------------------------------------------------------ read-only TCP downlink (core)
    def downlink_server(self):
        """Telemetry-only TCP port: the ground connects OUT to the Pi (no inbound firewall rule needed on the
        laptop). Anything received on this port is discarded -- it can never reach the FC."""
        from collections import deque

        port = int(self.cfg["bridge"].get("downlink_port", 14561))
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", port))
        srv.listen(4)
        while not self._stop.is_set():
            conn, addr = srv.accept()
            q: deque = deque(maxlen=400)
            self.uplink_queues[id(q)] = q

            def serve(conn=conn, q=q):
                conn.settimeout(0.05)
                try:
                    while not self._stop.is_set():
                        try:
                            if not conn.recv(4096):        # discard input; detect close
                                break
                        except socket.timeout:
                            pass
                        if q:
                            conn.sendall(b"".join(q.popleft() for _ in range(min(len(q), 50))))
                except OSError:
                    pass
                finally:
                    self.uplink_queues.pop(id(q), None)
                    conn.close()

            threading.Thread(target=serve, daemon=True).start()

    # ------------------------------------------------------------------ ground subscribe + pose publisher
    def subscribe_listener(self):
        port = int(self.cfg["bridge"].get("subscribe_port", 14552))
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("0.0.0.0", port))
        while not self._stop.is_set():
            data, addr = s.recvfrom(64)
            if data.startswith(b"CBSUB"):
                self.ground.add((addr[0], int(self.cfg["bridge"].get("ground_udp_port", 14551))))

    def publisher(self):
        while not self._stop.is_set():
            fit = self.clock.update()
            snap = dict(self.pose, t_pub_ns=boottime_ns(), clock=fit.to_dict() if fit else None,
                        stats=dict(self.stats, uplink=dict(self.filter.stats), ground=sorted(map(list, self.ground))))
            tmp = self.shm.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(snap))
                os.replace(tmp, self.shm)
            except OSError:
                pass
            if fit is not None and int(time.monotonic()) % 10 == 0:
                with open(self.session_dir / "clock.jsonl", "a") as f:
                    f.write(json.dumps(dict(t=boottime_ns(), **fit.to_dict())) + "\n")
            self._stop.wait(0.1)

    def run(self):
        for fn in (self.fc_loop, self.uplink_server, self.downlink_server, self.subscribe_listener, self.publisher):
            threading.Thread(target=fn, name=fn.__name__, daemon=True).start()
        while not self._stop.is_set():
            time.sleep(1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="/etc/cloudbreak/air.toml")
    a = ap.parse_args(argv)
    Bridge(load_air_config(a.config)).run()


if __name__ == "__main__":
    main()
