import math
import struct

import numpy as np

from cloudbreak.common.mav import MissionItem, mavlink, mission_hash
from cloudbreak.common.missions import LandingSpec, approach_geometry, landing_items, path_points, with_jump_back
from cloudbreak.common.timebase import FcClockModel

SPEC = LandingSpec(touchdown_lat=42.7303, touchdown_lon=-73.6798, heading_deg=200.0, touchdown_rel_alt_m=0.4)


def _ardupilot_roundtrip(items):
    """Mimic what ArduPilot 4.7.2 returns on read-back (verified in SITL)."""
    out = []
    f32 = lambda v: struct.unpack("<f", struct.pack("<f", v))[0]
    for it in items:
        frame = {6: 3, 5: 0, 11: 10}.get(it.frame, it.frame)
        if it.command == mavlink.MAV_CMD_DO_JUMP:
            frame = 0
        p = [f32(it.param1), f32(it.param2), f32(it.param3), f32(it.param4)]
        if it.command == mavlink.MAV_CMD_NAV_LOITER_TO_ALT:
            p[0] = 0.0
        if it.command == mavlink.MAV_CMD_NAV_LAND:
            p[3] = 1.0
        out.append(MissionItem(it.command, frame, *p, lat=it.x / 1e7, lon=it.y / 1e7, alt=f32(it.alt)))
    return out


def test_hash_survives_autopilot_roundtrip():
    items = with_jump_back(landing_items(SPEC), base_seq=1)
    assert mission_hash(items) == mission_hash(_ardupilot_roundtrip(items))


def test_hash_changes_with_any_relevant_field():
    a = mission_hash(landing_items(SPEC))
    for change in (dict(heading_deg=201.0), dict(touchdown_rel_alt_m=0.9), dict(touchdown_lat=42.73031)):
        b = mission_hash(landing_items(LandingSpec(**{**SPEC.to_dict(), **change})))
        assert a != b, change


def test_landing_geometry_glide_and_order():
    items = landing_items(SPEC)
    labels = [i.label for i in items]
    assert labels == ["hold", "look_a", "look_b", "jump_look", "entry", "final1", "final2", "touchdown", "goaround"]
    full = with_jump_back(items, base_seq=1)
    assert full[3].param1 == 1 and full[-1].param1 == 1        # both jumps return to the hold (seq 1)
    geo = approach_geometry(SPEC)
    assert math.isclose(geo["d_final1"] * SPEC.glide_slope_pct / 100, SPEC.approach_alt_m)
    td = items[labels.index("touchdown")]
    assert td.command == mavlink.MAV_CMD_NAV_LAND and math.isclose(td.alt, SPEC.touchdown_rel_alt_m)


def test_path_points_include_loiter_circles():
    pts = path_points(landing_items(SPEC), 42.7303, -73.6798)
    assert len(pts) > 150


def test_clock_model_recovers_offset_and_drift():
    rng = np.random.default_rng(0)
    m = FcClockModel(window_s=200)
    off, drift, lat_min = 5.0e9, 20e-6, 1.5e6
    for k in range(4000):
        pi = 1e10 + k * 0.04e9
        fc_true = pi - off - drift * (pi - 1e10)
        lat = lat_min + rng.exponential(4e6)
        t_rx = pi + lat
        fc_ms = math.floor(fc_true / 1e6)               # time_boot_ms quantisation
        m.add(int(t_rx), int(fc_ms * 1e6), 1_000_000)
    fit = m.update()
    pi_test = 1e10 + 3500 * 0.04e9
    fc_test = pi_test - off - drift * (pi_test - 1e10)
    err_ns = fit.fc_to_pi(fc_test) - pi_test
    assert abs(err_ns - lat_min) < 1.0e6, (err_ns, fit)   # within 1 ms of (true + min latency)
    assert abs(fit.drift_ppm - drift * 1e6) < 5
