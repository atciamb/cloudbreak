"""Signing proxy: byte-level signing/stripping against pymavlink, downlink checks, uplink policy, end to end."""
import os
import socket
import threading
import time

import pytest

os.environ.setdefault("MAVLINK20", "1")
from pymavlink.dialects.v20 import all as mavall  # noqa: E402

from cloudbreak.ground import gcs_proxy as gp  # noqa: E402

KEY = bytes(range(32))
OTHER = bytes(32)
OLD_TS = gp.signing_timestamp(time.time() - 6 * 3600)     # the real FC's clock sat 6 h behind (no GPS yet)


class Sink:
    def __init__(self):
        self.data = b""

    def write(self, b):
        self.data += b


def encoder(sysid=42, compid=1, key=None, ts=None):
    sink = Sink()
    mav = mavall.MAVLink(sink, srcSystem=sysid, srcComponent=compid)
    if key is not None:
        mav.signing.secret_key = key
        mav.signing.sign_outgoing = True
        mav.signing.timestamp = ts if ts is not None else gp.signing_timestamp()
        mav.signing.link_id = 0
    return mav, sink


def fc_heartbeat(key=KEY, ts=OLD_TS):
    mav, sink = encoder(key=key, ts=ts)
    mav.heartbeat_send(1, 3, 81, 0, 3)
    return sink.data


def parse_one(raw):
    fr = gp.FrameParser().feed(raw)
    assert len(fr) == 1
    return fr[0]


def test_parser_resyncs_through_noise_and_split_feeds():
    raw = fc_heartbeat() + fc_heartbeat(ts=OLD_TS + 5)
    p = gp.FrameParser()
    got = p.feed(b"\x00\xfd\x09garbage" + raw[:7]) + p.feed(raw[7:20]) + p.feed(raw[20:])
    assert [f.msgid for f in got] == [0, 0] and all(f.signed for f in got)
    assert p.noise > 0


def test_parser_reads_mavlink1():
    mav, sink = encoder(sysid=255, compid=190)
    mav.param_set_send(42, 1, b"SERVO1_FUNCTION", 70, 9, force_mavlink1=True)
    f = parse_one(sink.data)
    assert f.version == 1 and f.msgid == gp.MSG_PARAM_SET and f.sysid == 255


def test_strip_gives_a_plain_frame_pymavlink_accepts():
    raw = fc_heartbeat()
    f = parse_one(raw)
    assert gp.verify_signature(f, KEY) and not gp.verify_signature(f, OTHER)
    plain = gp.strip_signature(f)
    assert len(plain) == len(raw) - 13 and plain[2] == 0
    m = mavall.MAVLink(None).decode(bytearray(plain))          # a parser with no key, like Mission Planner
    assert m.get_type() == "HEARTBEAT" and m.get_srcSystem() == 42 and m.base_mode == 81


@pytest.mark.parametrize("v1", [False, True])
def test_signed_uplink_verifies_in_pymavlink(v1):
    mav, sink = encoder(sysid=255, compid=190)
    mav.param_set_send(42, 1, b"SERVO1_FUNCTION", 70, 9, force_mavlink1=v1)
    assert sink.data[0] == (0xFE if v1 else 0xFD)
    signed = gp.Signer(KEY).sign(parse_one(sink.data))
    rx = mavall.MAVLink(None)
    rx.signing.secret_key = KEY
    rx.signing.timestamp = gp.signing_timestamp() - 100
    m = rx.decode(bytearray(signed))
    assert m.get_type() == "PARAM_SET" and m.param_id == "SERVO1_FUNCTION" and m.param_value == 70
    assert m.get_srcSystem() == 255 and m.get_signed() and m.get_link_id() == gp.PROXY_LINK_ID
    rx2 = mavall.MAVLink(None)
    rx2.signing.secret_key = OTHER
    rx2.signing.timestamp = gp.signing_timestamp() - 100
    with pytest.raises(Exception):
        rx2.decode(bytearray(signed))


def test_signer_timestamps_strictly_increase():
    s = gp.Signer(KEY)
    mav, sink = encoder(sysid=255, compid=190)
    mav.heartbeat_send(6, 8, 0, 0, 4)
    f = parse_one(sink.data)
    stamps = [parse_one(s.sign(f)).sig_timestamp for _ in range(50)]
    assert all(b > a for a, b in zip(stamps, stamps[1:]))


def test_downlink_drops_bad_unsigned_and_replayed_then_reanchors():
    d = gp.Downlink(KEY, reanchor_s=2.0)
    assert d.accept(parse_one(fc_heartbeat(ts=OLD_TS)), now=0.0) is not None         # stale clock is fine
    assert d.accept(parse_one(fc_heartbeat(key=OTHER, ts=OLD_TS + 1)), now=0.1) is None
    mav, sink = encoder()
    mav.heartbeat_send(1, 3, 81, 0, 3)
    assert d.accept(parse_one(sink.data), now=0.2) is None                            # unsigned
    assert d.accept(parse_one(fc_heartbeat(ts=OLD_TS)), now=0.3) is None              # replay
    assert d.counts == dict(ok=1, bad_sig=1, unsigned=1, replay=1, reanchored=0, unknown_msg=0)
    # FC reboot: clock reloads an older value and counts up from there; accepted once it has run for 2 s
    for i, t in enumerate([1.0, 1.5, 2.9]):
        assert d.accept(parse_one(fc_heartbeat(ts=OLD_TS - 1000 + i)), now=t) is None
    assert d.accept(parse_one(fc_heartbeat(ts=OLD_TS - 990)), now=3.1) is not None
    assert d.counts["reanchored"] == 1 and d.notes


def _frame(fn, *args, sysid=255):
    mav, sink = encoder(sysid=sysid, compid=190)
    getattr(mav, fn)(*args)
    return parse_one(sink.data)


def test_policy_never_forwards_setup_signing_or_fc_sysid():
    p = gp.UplinkPolicy()
    assert not p.check(_frame("setup_signing_send", 42, 1, list(OTHER), 0))[0]
    assert not p.check(_frame("heartbeat_send", 1, 3, 81, 0, 3, sysid=42))[0]
    assert p.check(_frame("param_set_send", 42, 1, b"SERVO1_FUNCTION", 70, 9))[0]
    assert p.describe(_frame("param_set_send", 42, 1, b"SERVO1_FUNCTION", 70, 9)) == "PARAM_SET SERVO1_FUNCTION = 70"


def test_read_only_policy():
    p = gp.UplinkPolicy(read_only=True)
    arm = _frame("command_long_send", 42, 1, mavall.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0)
    req = _frame("command_long_send", 42, 1, mavall.MAV_CMD_REQUEST_MESSAGE, 0, 148, 0, 0, 0, 0, 0, 0)
    cint = _frame("command_int_send", 42, 1, 0, mavall.MAV_CMD_DO_SET_MODE, 0, 0, 1, 10, 0, 0, 0, 0, 0)
    assert not p.check(arm)[0] and p.check(req)[0] and not p.check(cint)[0]
    assert not p.check(_frame("param_set_send", 42, 1, b"FENCE_ENABLE", 0, 9))[0]
    assert p.check(_frame("param_request_list_send", 42, 1))[0]
    assert p.check(_frame("heartbeat_send", 6, 8, 0, 0, 4))[0]
    assert "COMPONENT_ARM_DISARM" in gp.UplinkPolicy().describe(arm)


def test_end_to_end_with_a_fake_signed_fc():
    """Fake FC on TCP signs with a stale clock; a key-less 'Mission Planner' on UDP sees plain frames, and its
    unsigned PARAM_SET reaches the FC signed with the key. SETUP_SIGNING never reaches the FC."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    fc_port = srv.getsockname()[1]
    gcs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gcs.bind(("127.0.0.1", 0))
    gcs.settimeout(3)
    received = []
    stop = threading.Event()

    def fake_fc():
        conn, _ = srv.accept()
        conn.settimeout(0.1)
        mav, sink = encoder(key=KEY, ts=OLD_TS)
        parser = gp.FrameParser()
        while not stop.is_set():
            sink.data = b""
            mav.heartbeat_send(1, 3, 81, 0, 3)
            conn.sendall(sink.data)
            try:
                received.extend(parser.feed(conn.recv(4096)))
            except socket.timeout:
                pass
        conn.close()

    th = threading.Thread(target=fake_fc, daemon=True)
    th.start()
    proxy = gp.Proxy(f"tcp:127.0.0.1:{fc_port}", KEY, udp_gcs=gcs.getsockname(), tcp_listen=None, quiet=True)
    proxy.start()
    try:
        data, proxy_addr = gcs.recvfrom(4096)
        m = mavall.MAVLink(None).decode(bytearray(data))
        assert m.get_type() == "HEARTBEAT" and not m.get_signed()
        mav, sink = encoder(sysid=255, compid=190)
        mav.param_set_send(42, 1, b"SERVO1_FUNCTION", 70, 9, force_mavlink1=True)    # MP starts out in v1
        mav.setup_signing_send(42, 1, list(OTHER), 0)
        gcs.sendto(sink.data, proxy_addr)
        t0 = time.time()
        while time.time() - t0 < 3 and not received:
            time.sleep(0.05)
        time.sleep(0.3)
        assert [f.msgid for f in received] == [gp.MSG_PARAM_SET]
        assert received[0].signed and gp.verify_signature(received[0], KEY)
        assert proxy.up["refused"] == 1
    finally:
        stop.set()
        proxy.close()
        gcs.close()
        srv.close()
