"""Stabilized-approach gate (pure functions; used by the governor while a landing is committed).

Below the decision point (short final, MISSION_CURRENT = NAV_LAND) the aircraft must be lined up with the strip:
  * cross-track error <= xtrack_max_m      (strip half-width minus half the wingspan)
  * track within track_err_max_deg of the landing heading (when moving)
  * height within height_err_max_m of the glide path (checked above flare height only)
If any of these fails, the governor commands DO_GO_AROUND. After `max_unstable` unstable approaches it stops
offering commits: the autoland is abandoned and the pilot lands manually.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from cloudbreak.common.geodesy import enu_offset


@dataclass(frozen=True)
class GateConfig:
    xtrack_max_m: float = 7.0
    track_err_max_deg: float = 20.0
    height_err_max_m: float = 5.0
    flare_alt_m: float = 4.0          # below this (above touchdown) only the cross-track limit is applied
    min_groundspeed_mps: float = 4.0  # track angle is meaningless when (nearly) stopped
    max_unstable: int = 2


@dataclass
class ApproachState:
    along_m: float        # + = past touchdown along the landing heading
    cross_m: float        # + = right of the centreline
    track_err_deg: float | None
    height_err_m: float   # + = above the glide path
    height_above_td_m: float


def approach_state(spec: dict, lat: float, lon: float, rel_alt_m: float, vn: float, ve: float) -> ApproachState:
    h = math.radians(spec["heading_deg"])
    de, dn = enu_offset(spec["touchdown_lat"], spec["touchdown_lon"], lat, lon)
    along = de * math.sin(h) + dn * math.cos(h)
    cross = de * math.cos(h) - dn * math.sin(h)
    gs = math.hypot(vn, ve)
    track_err = None
    if gs > 0.1:
        trk = math.degrees(math.atan2(ve, vn))
        track_err = (trk - spec["heading_deg"] + 180.0) % 360.0 - 180.0
    above_td = rel_alt_m - spec["touchdown_rel_alt_m"]
    glide = spec["glide_slope_pct"] / 100.0 * max(0.0, -along)
    return ApproachState(along, cross, track_err, above_td - glide, above_td)


def gate_violation(st: ApproachState, groundspeed: float, cfg: GateConfig) -> str | None:
    """None if the approach is stable, else a human-readable reason."""
    if abs(st.cross_m) > cfg.xtrack_max_m:
        return f"cross-track {st.cross_m:+.1f} m (limit {cfg.xtrack_max_m:.0f} m)"
    if st.height_above_td_m > cfg.flare_alt_m:
        if st.track_err_deg is not None and groundspeed >= cfg.min_groundspeed_mps and abs(st.track_err_deg) > cfg.track_err_max_deg:
            return f"track error {st.track_err_deg:+.0f} deg (limit {cfg.track_err_max_deg:.0f})"
        if abs(st.height_err_m) > cfg.height_err_max_m:
            return f"{'high' if st.height_err_m > 0 else 'low'} on glide path by {abs(st.height_err_m):.1f} m (limit {cfg.height_err_max_m:.0f} m)"
    return None


def look_start_ok(spec: dict, lat: float, lon: float, vn: float, ve: float, max_dist_m: float = 45.0,
                  max_track_err_deg: float = 45.0) -> bool:
    """Circuit pattern: start the last look only near the hold circle's tangent point with the aircraft already
    moving in the landing direction, so it flows straight onto the centreline. Started from the far side of the
    circle, ArduPlane can end up orbiting the first look waypoint."""
    from cloudbreak.common.missions import LandingSpec, _circuit_geometry

    g = _circuit_geometry(LandingSpec(**spec))
    h = math.radians(spec["heading_deg"])
    de, dn = enu_offset(spec["touchdown_lat"], spec["touchdown_lon"], lat, lon)
    along = de * math.sin(h) + dn * math.cos(h)
    cross = de * math.cos(h) - dn * math.sin(h)
    if math.hypot(along - g["t_along"], cross) > max_dist_m or math.hypot(vn, ve) < 3.0:
        return False
    trk = math.degrees(math.atan2(ve, vn))
    return abs((trk - spec["heading_deg"] + 180.0) % 360.0 - 180.0) <= max_track_err_deg
