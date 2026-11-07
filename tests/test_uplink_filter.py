import os

os.environ.setdefault("MAVLINK20", "1")
from pymavlink.dialects.v20 import ardupilotmega as m2  # noqa: E402

from cloudbreak.air.uplink_filter import CMD, PLANE_MODE, UplinkFilter  # noqa: E402

KEY = bytes(range(32))


def _tx(sysid=245, signed=True):
    tx = m2.MAVLink(None, srcSystem=sysid, srcComponent=190)
    if signed:
        tx.signing.secret_key = KEY
        tx.signing.sign_outgoing = True
        tx.signing.link_id = 0
        tx.signing.timestamp = 1
    return tx


def _roundtrip(tx, msg):
    buf = msg.pack(tx)
    rx = m2.MAVLink(None)
    rx.robust_parsing = True
    out = rx.parse_buffer(buf)
    assert out and len(out) == 1, out
    return out[0]


def check(msg, **kw):
    return UplinkFilter().check(_roundtrip(_tx(**kw), msg))


def test_signed_allowlisted_command_forwarded():
    v = check(m2.MAVLink_command_long_message(1, 1, CMD["DO_GO_AROUND"], 0, 30, 0, 0, 0, 0, 0, 0))
    assert v.forward, v


def test_unsigned_dropped():
    v = check(m2.MAVLink_command_long_message(1, 1, CMD["DO_GO_AROUND"], 0, 30, 0, 0, 0, 0, 0, 0), signed=False)
    assert not v.forward and v.reason == "unsigned"


def test_wrong_sysid_dropped():
    v = check(m2.MAVLink_heartbeat_message(6, 8, 0, 0, 4, 3), sysid=255)
    assert not v.forward


def test_arm_disarm_never_forwarded():
    v = check(m2.MAVLink_command_long_message(1, 1, CMD["COMPONENT_ARM_DISARM"], 0, 1, 0, 0, 0, 0, 0, 0))
    assert not v.forward and v.reason.startswith("cmd")


def test_param_set_never_forwarded():
    v = check(m2.MAVLink_param_set_message(1, 1, b"FENCE_ENABLE", 0.0, 9))
    assert not v.forward


def test_rc_override_never_forwarded():
    v = check(m2.MAVLink_rc_channels_override_message(1, 1, 0, 0, 2000, 0, 0, 0, 0, 0))
    assert not v.forward


def test_mode_change_only_auto_or_rtl():
    ok = check(m2.MAVLink_command_long_message(1, 1, CMD["DO_SET_MODE"], 0, 1, PLANE_MODE["RTL"], 0, 0, 0, 0, 0))
    bad = check(m2.MAVLink_command_long_message(1, 1, CMD["DO_SET_MODE"], 0, 1, PLANE_MODE["MANUAL"], 0, 0, 0, 0, 0))
    assert ok.forward and not bad.forward


def test_mission_item_int_forwarded_mission_item_float_dropped():
    good = check(m2.MAVLink_mission_item_int_message(1, 1, 1, 6, 16, 0, 1, 0, 0, 0, 0, 427303000, -736798000, 40, 0))
    bad = check(m2.MAVLink_mission_item_message(1, 1, 1, 3, 16, 0, 1, 0, 0, 0, 0, 42.73, -73.68, 40, 0))
    assert good.forward and not bad.forward


def _param_set(name=b"FENCE_ENABLE", value=1.0):
    return _roundtrip(_tx(), m2.MAVLink_param_set_message(42, 1, name, value, 9))


def _maint_filter(window_s=300.0, armed=False, hb_age_s=0.5):
    import time
    f = UplinkFilter()
    f.maintenance_until = time.time() + window_s
    f.fc_armed = armed
    f.fc_hb_mono = time.monotonic() - hb_age_s
    return f


def test_param_set_forwarded_in_window_when_disarmed():
    v = _maint_filter().check(_param_set())
    assert v.forward, v


def test_param_set_dropped_when_armed_or_stale_or_no_window():
    assert _maint_filter(armed=True).check(_param_set()).reason == "param armed"
    assert _maint_filter(hb_age_s=10).check(_param_set()).reason == "param no-fresh-heartbeat"
    assert _maint_filter(window_s=-1).check(_param_set()).reason == "msg PARAM_SET"
    assert _maint_filter(window_s=3600).check(_param_set()).reason == "msg PARAM_SET"     # longer than MAINT_MAX_S
    f = UplinkFilter()
    f.fc_armed, f.fc_hb_mono = False, __import__("time").monotonic()
    assert not f.check(_param_set()).forward                                             # never opened


def test_link_and_arming_params_denied_even_in_window():
    for name in (b"SERIAL4_BAUD", b"MAV_SYSID", b"MAV_GCS_SYSID", b"ARMING_SKIPCHK", b"MAV3_OPTIONS"):
        v = _maint_filter().check(_param_set(name))
        assert not v.forward and v.reason.startswith("param denied"), (name, v)


def test_param_set_unsigned_still_dropped_in_window():
    msg = _roundtrip(_tx(signed=False), m2.MAVLink_param_set_message(42, 1, b"FENCE_ENABLE", 1.0, 9))
    assert _maint_filter().check(msg).reason == "unsigned"


def test_rate_limit():
    f = UplinkFilter(max_per_s=5)
    tx = _tx()
    res = [f.check(_roundtrip(tx, m2.MAVLink_heartbeat_message(6, 8, 0, 0, 4, 3))).forward for _ in range(10)]
    assert res[:5] == [True] * 5 and not any(res[5:])
