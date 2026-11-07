"""Site geofence: one inclusion polygon per site, shared by the FC setup tool, the planner and the governor.

The polygon in config/site_<key>.toml [fence] is what gets uploaded to the autopilot (FENCE_TYPE polygon bit,
FENCE_ACTION=RTL). A breach makes ArduPlane fly RTL, so a governed mission that grazes the fence would turn into an
unplanned RTL in the middle of an approach. The planner and the governor therefore require every planned path point
to be at least `path_margin_m` inside the polygon and below `alt_max_m - alt_margin_m`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from shapely.geometry import Point, Polygon

from cloudbreak.common.geodesy import lonlat_to_utm


@dataclass
class Fence:
    polygon_latlon: list[tuple[float, float]]
    alt_max_m: float
    path_margin_m: float = 20.0
    alt_margin_m: float = 10.0

    def utm_polygon(self) -> Polygon:
        return Polygon([lonlat_to_utm(lon, lat) for lat, lon in self.polygon_latlon])


@dataclass
class FenceResult:
    ok: bool
    worst_margin_m: float      # smallest distance inside the polygon (negative = outside)
    max_alt_m: float
    reason: str


def site_fence(site_cfg: dict) -> Fence | None:
    f = site_cfg.get("fence")
    if not f or not f.get("polygon"):
        return None
    poly = [(float(a), float(b)) for a, b in f["polygon"]]
    if len(poly) < 3:
        raise ValueError("fence polygon needs at least 3 vertices")
    fence = Fence(poly, float(f["alt_max_m"]), float(f.get("path_margin_m", 20.0)), float(f.get("alt_margin_m", 10.0)))
    if not fence.utm_polygon().is_valid:
        raise ValueError("fence polygon is self-intersecting")
    return fence


def check_path(points: Iterable[tuple[float, float, float]], fence: Fence) -> FenceResult:
    """`points` are (lat, lon, rel_alt_m). OK only if every point is >= path_margin_m inside the polygon and
    <= alt_max_m - alt_margin_m."""
    poly = fence.utm_polygon()
    worst, worst_pt, max_alt = math.inf, None, -math.inf
    for lat, lon, alt in points:
        p = Point(*lonlat_to_utm(lon, lat))
        d = poly.exterior.distance(p) * (1.0 if poly.contains(p) else -1.0)
        if d < worst:
            worst, worst_pt = d, (lat, lon)
        max_alt = max(max_alt, alt)
    if worst_pt is None:
        return FenceResult(False, -math.inf, max_alt, "empty path")
    if worst < fence.path_margin_m:
        where = "outside" if worst < 0 else "too close to"
        return FenceResult(False, worst, max_alt,
                           f"path {where} the geofence: {worst:.0f} m at {worst_pt[0]:.6f},{worst_pt[1]:.6f} "
                           f"(needs >= {fence.path_margin_m:.0f} m inside)")
    if max_alt > fence.alt_max_m - fence.alt_margin_m:
        return FenceResult(False, worst, max_alt, f"path reaches {max_alt:.0f} m, fence ceiling {fence.alt_max_m:.0f} m "
                                                  f"(needs {fence.alt_margin_m:.0f} m below)")
    return FenceResult(True, worst, max_alt, f"inside geofence by >= {worst:.0f} m, max alt {max_alt:.0f} m")
