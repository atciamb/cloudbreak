import math

from cloudbreak.common.fence import Fence, check_path
from cloudbreak.common.geodesy import enu_offset, offset_latlon
from cloudbreak.common.mav import mavlink
from cloudbreak.common.missions import (LandingSpec, _circuit_geometry, landing_items, landing_path_points,
                                        survey_items_fenced, survey_path_points, with_jump_back)
from cloudbreak.ground.governor.approach import GateConfig, approach_state, gate_violation, look_start_ok

TD = (42.7059, -73.7100)


def spec(side=-1, hdg=90.0):
    return LandingSpec(TD[0], TD[1], hdg, 0.0, hold_alt_m=40.0, hold_radius_m=40.0, hold_offset_m=10.2, approach_alt_m=15.0,
                       short_final_alt_m=7.5, glide_slope_pct=12.0, entry_radius_m=40.0, goaround_alt_m=25.0,
                       abort_alt_m=25.0, look_half_m=45.5, turn_radius_m=50.0, entry_lead_m=40.0, pattern="circuit", side=side)


def along_cross(sp, lat, lon):
    h = math.radians(sp.heading_deg)
    de, dn = enu_offset(sp.touchdown_lat, sp.touchdown_lon, lat, lon)
    return de * math.sin(h) + dn * math.cos(h), de * math.cos(h) - dn * math.sin(h)


def test_circuit_items_order_and_loiter_direction():
    for side, sign in ((-1, -1), (1, 1)):
        items = landing_items(spec(side))
        assert [i.label for i in items] == ["hold", "look_a", "look_b", "dw", "jump_look", "entry", "final1", "final2",
                                            "touchdown", "goaround"]
        hold, entry = items[0], items[5]
        assert math.copysign(1, hold.param3) == sign and math.copysign(1, entry.param2) == sign   # left = CCW
        assert abs(hold.param3) == 40.0                                  # commanded radius


def test_circle_is_tangent_to_the_centreline_at_the_flown_radius():
    sp = spec(-1)
    g = _circuit_geometry(sp)
    hold = landing_items(sp)[0]
    a, c = along_cross(sp, hold.lat, hold.lon)
    assert abs(a - g["t_along"]) < 0.5 and abs(c - (-50.0)) < 0.5      # centre one FLOWN radius left of the line
    assert abs(g["t_along"] + (15.0 / 0.12 + 40.0)) < 1e-6             # final1 distance + roll-out


def test_go_around_joins_the_downwind_and_look_returns_to_hold():
    items = with_jump_back(landing_items(spec()), base_seq=1)
    idx = {it.label: i + 1 for i, it in enumerate(items)}
    assert items[-1].label == "jump_hold" and items[-1].param1 == idx["dw"]
    assert next(i for i in items if i.label == "jump_look").param1 == idx["hold"]


def test_circuit_footprint_is_one_sided():
    for side in (-1, 1):
        sp = spec(side)
        crosses = [along_cross(sp, la, lo)[1] for la, lo, _ in landing_path_points(sp)]
        if side < 0:
            assert max(crosses) < 1.0 and min(crosses) > -101.0
        else:
            assert min(crosses) > -1.0 and max(crosses) < 101.0


def test_gate_stable_on_glide_path_and_rejects_offsets():
    sp = spec().to_dict()
    gate = GateConfig()
    on = lambda a, c, alt, trk=90.0: approach_state(sp, *offset_latlon(TD[0], TD[1], a * math.sin(math.radians(90)) + c * math.cos(math.radians(90)),  # noqa: E731
                                                                        a * math.cos(math.radians(90)) - c * math.sin(math.radians(90))),
                                                    alt, 13 * math.cos(math.radians(trk)), 13 * math.sin(math.radians(trk)))
    assert gate_violation(on(-40, 0.0, 4.8), 13, gate) is None                     # on the 12 % path
    assert "cross-track" in gate_violation(on(-40, 9.0, 4.8), 13, gate)
    assert "track error" in gate_violation(on(-40, 0.0, 4.8, trk=120), 13, gate)
    assert "high" in gate_violation(on(-40, 0.0, 12.0), 13, gate)
    assert gate_violation(on(-5, 3.0, 2.0, trk=130), 13, gate) is None             # in the flare: only cross-track


def test_look_starts_only_near_the_tangent_point_heading_down_the_runway():
    sp = spec(-1)
    g = _circuit_geometry(sp)
    lat, lon = offset_latlon(TD[0], TD[1], g["t_along"], 0.0)                        # hdg 90: along = east
    assert look_start_ok(sp.to_dict(), lat, lon, 0.0, 13.0)
    assert not look_start_ok(sp.to_dict(), lat, lon, 0.0, -13.0)                     # flying the wrong way
    far = offset_latlon(TD[0], TD[1], g["t_along"], 100.0)
    assert not look_start_ok(sp.to_dict(), *far, 0.0, 13.0)


def test_fenced_survey_turns_stay_inside_the_fence():
    lat0, lon0 = 42.7050, -73.7100
    sq = [offset_latlon(lat0, lon0, e, n) for e, n in ((-220, -220), (220, -220), (220, 220), (-220, 220))]
    f = Fence(sq, alt_max_m=100.0, path_margin_m=20.0)
    items = survey_items_fenced(lat0, lon0, 84.0, 91.0, 0.0, 45.0, 14.0, 50.0, sq, 20.0, 50.0)
    assert len(items) >= 4 and all(it.command == mavlink.MAV_CMD_NAV_WAYPOINT for it in items)
    assert check_path(survey_path_points(items, 50.0), f).ok
    tight = [offset_latlon(lat0, lon0, e, n) for e, n in ((-120, -120), (120, -120), (120, 120), (-120, 120))]
    t_items = survey_items_fenced(lat0, lon0, 84.0, 91.0, 0.0, 45.0, 14.0, 50.0, tight, 20.0, 50.0)
    assert t_items and check_path(survey_path_points(t_items, 50.0), Fence(tight, 100.0, 20.0)).ok   # shorter lines, still inside
    tiny = [offset_latlon(lat0, lon0, e, n) for e, n in ((-80, -80), (80, -80), (80, 80), (-80, 80))]
    assert survey_items_fenced(lat0, lon0, 84.0, 91.0, 0.0, 45.0, 14.0, 50.0, tiny, 20.0, 50.0) == []   # nothing fits
