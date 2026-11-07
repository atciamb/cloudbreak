"""Deterministic ArduPlane mission construction (shared by planner and governor).

The governor never trusts a mission it is handed: it rebuilds it from (LandingSpec, params) with this
module and hashes the result. Same inputs -> same items -> same hash.

Landing sequence (hold-and-commit). No DO_LAND_START on purpose: 4.7.2 refuses to arm with a
DO_LAND_START unless RTL_AUTOLAND is set, and RTL_AUTOLAND would turn a link-loss RTL into a landing.
Aborts resume at the CONTINUE_AND_CHANGE_ALT item, so DO_LAND_START isn't needed.
    NAV_LOITER_UNLIM  "hold"   -- plane waits here; camera takes the last look; governor commits by
                                   jumping to the next item with DO_SET_MISSION_CURRENT
    NAV_LOITER_TO_ALT "entry"  -- descend to approach altitude on the extended centreline, exit on heading
    NAV_WAYPOINT  "final1"     -- glide path start
    NAV_WAYPOINT  "final2"     -- short final
    NAV_LAND      "touchdown"  -- param1 = abort climb altitude
    NAV_CONTINUE_AND_CHANGE_ALT "goaround"  -- defines go-around (abort resumes here)
    DO_JUMP -> hold            -- after a go-around the plane returns to the hold and waits again
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from cloudbreak.common.geodesy import offset_latlon
from cloudbreak.common.mav import FRAME_REL_ALT_INT, MissionItem, mavlink


@dataclass(frozen=True)
class LandingSpec:
    """Everything the mission depends on. Hash-relevant: change any field -> new mission hash."""

    touchdown_lat: float
    touchdown_lon: float
    heading_deg: float            # landing direction (true), i.e. direction of travel on final
    touchdown_rel_alt_m: float    # DTM(touchdown) - DTM(home) + baro bias correction
    hold_alt_m: float = 40.0
    hold_radius_m: float = 45.0
    hold_offset_m: float = 0.0    # hold centre distance from touchdown along the strip (+ = ahead)
    approach_alt_m: float = 25.0  # altitude at final1, relative to touchdown
    short_final_alt_m: float = 8.0
    glide_slope_pct: float = 8.0  # <= 10 % per ArduPilot guidance
    entry_radius_m: float = 40.0
    goaround_alt_m: float = 40.0
    abort_alt_m: float = 30.0
    look_half_m: float = 110.0    # last-look leg extends this far either side of the strip centre

    def to_dict(self):
        return asdict(self)


def _along(spec: LandingSpec, dist_m: float, lateral_m: float = 0.0):
    """Point `dist_m` ahead of touchdown along the landing heading (negative = before touchdown)."""
    h = math.radians(spec.heading_deg)
    de = dist_m * math.sin(h) + lateral_m * math.cos(h)
    dn = dist_m * math.cos(h) - lateral_m * math.sin(h)
    return offset_latlon(spec.touchdown_lat, spec.touchdown_lon, de, dn)


def approach_geometry(spec: LandingSpec) -> dict:
    g = spec.glide_slope_pct / 100.0
    d1 = spec.approach_alt_m / g
    d2 = spec.short_final_alt_m / g
    d_entry = d1 + spec.entry_radius_m * 1.5
    return dict(d_final1=d1, d_final2=d2, d_entry=d_entry, glide_rad=math.atan(g))


def landing_items(spec: LandingSpec) -> list[MissionItem]:
    geo = approach_geometry(spec)
    td = spec.touchdown_rel_alt_m
    ent_lat, ent_lon = _along(spec, -geo["d_entry"])
    f1_lat, f1_lon = _along(spec, -geo["d_final1"])
    f2_lat, f2_lon = _along(spec, -geo["d_final2"])
    hold_lat, hold_lon = _along(spec, spec.hold_offset_m)
    la_lat, la_lon = _along(spec, spec.hold_offset_m - spec.look_half_m)
    lb_lat, lb_lon = _along(spec, spec.hold_offset_m + spec.look_half_m)
    ga_lat, ga_lon = _along(spec, 200.0)
    C = mavlink
    items = [
        MissionItem(C.MAV_CMD_NAV_LOITER_UNLIM, param3=spec.hold_radius_m, lat=hold_lat, lon=hold_lon,
                    alt=td + spec.hold_alt_m, label="hold"),
        # LAST LOOK: a straight, wings-level overflight of the strip along its axis (a nadir camera cannot see
        # the point a loiter circles). Triggered from the hold by the governor; returns to the hold.
        MissionItem(C.MAV_CMD_NAV_WAYPOINT, lat=la_lat, lon=la_lon, alt=td + spec.hold_alt_m, label="look_a"),
        MissionItem(C.MAV_CMD_NAV_WAYPOINT, lat=lb_lat, lon=lb_lon, alt=td + spec.hold_alt_m, label="look_b"),
        MissionItem(C.MAV_CMD_DO_JUMP, frame=C.MAV_FRAME_GLOBAL, param1=0, param2=-1, label="jump_look"),
        MissionItem(C.MAV_CMD_NAV_LOITER_TO_ALT, param2=spec.entry_radius_m, lat=ent_lat, lon=ent_lon,
                    alt=td + spec.approach_alt_m, label="entry"),
        MissionItem(C.MAV_CMD_NAV_WAYPOINT, lat=f1_lat, lon=f1_lon, alt=td + spec.approach_alt_m, label="final1"),
        MissionItem(C.MAV_CMD_NAV_WAYPOINT, lat=f2_lat, lon=f2_lon, alt=td + spec.short_final_alt_m, label="final2"),
        MissionItem(C.MAV_CMD_NAV_LAND, param1=spec.abort_alt_m, lat=spec.touchdown_lat, lon=spec.touchdown_lon,
                    alt=td, label="touchdown"),
        MissionItem(C.MAV_CMD_NAV_CONTINUE_AND_CHANGE_ALT, param1=1, lat=ga_lat, lon=ga_lon,
                    alt=td + spec.goaround_alt_m, label="goaround"),
    ]
    return items


def with_jump_back(items: list[MissionItem], base_seq: int) -> list[MissionItem]:
    """Resolve DO_JUMP targets to the hold item and append the post-go-around jump. base_seq = seq of items[0]."""
    hold_idx = next(i for i, it in enumerate(items) if it.label == "hold")
    for it in items:
        if it.label == "jump_look":
            it.param1 = base_seq + hold_idx
    return items + [MissionItem(mavlink.MAV_CMD_DO_JUMP, frame=mavlink.MAV_FRAME_GLOBAL, param1=base_seq + hold_idx,
                                param2=-1, label="jump_hold")]


def takeoff_items(alt_m: float = 40.0, pitch_deg: float = 12.0) -> list[MissionItem]:
    """SITL / auto-launch only. The real Tutor is launched by the pilot in FBWA."""
    return [MissionItem(mavlink.MAV_CMD_NAV_TAKEOFF, param1=pitch_deg, alt=alt_m, label="takeoff")]


def survey_items(lat0: float, lon0: float, width_m: float, length_m: float, heading_deg: float, alt_m: float,
                 spacing_m: float, lead_in_m: float = 60.0, min_turn_m: float = 45.0) -> list[MissionItem]:
    """Survey lines over a rectangle centred on (lat0, lon0), lines along `heading_deg`.

    Fixed-wing aware: consecutive lines are at least `min_turn_m` apart (~2x turn radius) by INTERLEAVING the
    line order (e.g. 0,4,1,5,2,6,3), and lead-ins let the plane settle on each line before the area of interest.
    A plain lawnmower with spacing << turn radius makes the plane loop wide and miss the lines."""
    n = max(1, int(math.ceil(width_m / spacing_m)) + 1)
    h = math.radians(heading_deg)
    ux, uy = math.sin(h), math.cos(h)          # along-line unit (east, north)
    vx, vy = math.cos(h), -math.sin(h)         # cross-line unit
    step = width_m / max(1, n - 1) if n > 1 else 0.0
    k = max(1, int(math.ceil(min_turn_m / step))) if step > 0 else 1
    order = []
    for start in range(k):
        order += list(range(start, n, k))
    items = []
    for j, i in enumerate(order):
        off = -width_m / 2 + i * step if n > 1 else 0.0
        a, b = -(length_m / 2 + lead_in_m), (length_m / 2 + lead_in_m)
        if j % 2:
            a, b = b, a
        for s in (a, b):
            de, dn = s * ux + off * vx, s * uy + off * vy
            lat, lon = offset_latlon(lat0, lon0, de, dn)
            items.append(MissionItem(mavlink.MAV_CMD_NAV_WAYPOINT, lat=lat, lon=lon, alt=alt_m, label=f"survey_{i}"))
    return items


def landing_path_points(spec: LandingSpec, climb_gradient: float = 0.15, step_m: float = 5.0):
    """Flight path for clearance checks of a landing sequence:
    hold circle -> entry circle -> final1 -> final2 -> touchdown, plus the MISSED APPROACH flown from the
    decision point (final2) climbing at `climb_gradient` along the landing heading to the go-around altitude.
    (A go-around below the decision height is the pilot's call; the plan must not depend on it.)"""
    items = landing_items(spec)
    by = {it.label: it for it in items}
    pts = path_points([by["hold"], by["look_a"], by["look_b"], by["entry"], by["final1"], by["final2"], by["touchdown"]],
                      0, 0, step_m)
    f2 = by["final2"]
    geo = approach_geometry(spec)
    s = 0.0
    td = spec.touchdown_rel_alt_m
    while True:
        alt = f2.alt + climb_gradient * s
        lat, lon = _along(spec, -geo["d_final2"] + s)
        pts.append((lat, lon, min(alt, td + spec.goaround_alt_m)))
        if alt >= td + spec.goaround_alt_m or s > 800:
            break
        s += step_m
    return pts


def path_points(items: list[MissionItem], home_lat: float, home_lon: float, step_m: float = 5.0):
    """Densified (lat, lon, rel_alt) polyline through positional items, for clearance/geofence checks.
    Loiters are expanded to their circle so turns are checked, not just waypoint centres."""
    pts = []
    prev = None
    for it in items:
        if it.command in (mavlink.MAV_CMD_DO_LAND_START, mavlink.MAV_CMD_DO_JUMP):
            continue
        if it.lat == 0.0 and it.lon == 0.0:      # e.g. NAV_TAKEOFF: flown from the current position
            continue
        cur = (it.lat, it.lon, it.alt)
        if it.command in (mavlink.MAV_CMD_NAV_LOITER_UNLIM, mavlink.MAV_CMD_NAV_LOITER_TO_ALT):
            r = it.param3 if it.command == mavlink.MAV_CMD_NAV_LOITER_UNLIM else it.param2
            r = abs(r) or 60.0
            for k in range(72):
                a = 2 * math.pi * k / 72
                pts.append((*offset_latlon(it.lat, it.lon, r * math.sin(a), r * math.cos(a)), it.alt))
        if prev is not None:
            from cloudbreak.common.geodesy import enu_offset

            de, dn = enu_offset(prev[0], prev[1], cur[0], cur[1])
            dist = math.hypot(de, dn)
            n = max(1, int(dist / step_m))
            for k in range(1, n + 1):
                f = k / n
                lat, lon = offset_latlon(prev[0], prev[1], de * f, dn * f)
                pts.append((lat, lon, prev[2] + (cur[2] - prev[2]) * f))
        else:
            pts.append(cur)
        prev = cur
    return pts
