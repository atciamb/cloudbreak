import math

import pytest

from cloudbreak.common.config import load_toml
from cloudbreak.common.fence import Fence, check_path, site_fence
from cloudbreak.common.geodesy import offset_latlon

LAT0, LON0 = 42.7050, -73.7100


def square(half_m: float) -> list[tuple[float, float]]:
    return [offset_latlon(LAT0, LON0, e, n) for e, n in ((-half_m, -half_m), (half_m, -half_m), (half_m, half_m), (-half_m, half_m))]


def line(e0, e1, alt=40.0, n=0.0, steps=20):
    return [(*offset_latlon(LAT0, LON0, e0 + (e1 - e0) * i / steps, n), alt) for i in range(steps + 1)]


FENCE = Fence(square(200.0), alt_max_m=100.0, path_margin_m=20.0, alt_margin_m=10.0)


def test_path_well_inside_passes():
    r = check_path(line(-150, 150), FENCE)
    assert r.ok and r.worst_margin_m == pytest.approx(50.0, abs=1.0)


def test_path_too_close_to_edge_fails():
    r = check_path(line(-190, 0), FENCE)
    assert not r.ok and "too close" in r.reason and r.worst_margin_m == pytest.approx(10.0, abs=1.0)


def test_path_outside_fails_with_negative_margin():
    r = check_path(line(0, 260), FENCE)
    assert not r.ok and "outside" in r.reason and r.worst_margin_m < 0


def test_altitude_ceiling_margin():
    assert check_path(line(-50, 50, alt=89.0), FENCE).ok
    r = check_path(line(-50, 50, alt=95.0), FENCE)
    assert not r.ok and "ceiling" in r.reason


def test_site_without_fence_returns_none():
    assert site_fence({"site": {}}) is None


def test_self_intersecting_polygon_rejected():
    a, b, c, d = square(100.0)
    with pytest.raises(ValueError):
        site_fence({"fence": {"alt_max_m": 100, "polygon": [a, c, b, d]}})


def test_schuyler_fence_loads_and_rejects_the_old_northbound_pattern():
    from cloudbreak.common.missions import LandingSpec, landing_path_points

    f = site_fence(load_toml("site_schuyler.toml"))
    assert f is not None and 3 <= len(f.polygon_latlon) <= 70      # well within ArduPilot's fence storage
    assert f.alt_max_m <= 121.9                                     # 400 ft facility-map ceiling
    ls = LandingSpec(42.7064, -73.7100, 0.0, 0.0, hold_alt_m=40.0, approach_alt_m=20.0, glide_slope_pct=12.0)
    r = check_path(landing_path_points(ls, 0.15), f)
    assert not r.ok and math.isfinite(r.worst_margin_m)            # its go-around climbs north over the houses
