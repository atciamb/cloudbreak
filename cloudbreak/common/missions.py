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
    turn_radius_m: float = 35.0   # ground radius of the 180 deg turns at the look-leg ends and after a go-around
    entry_lead_m: float = 0.0     # legacy: entry-circle centre this far behind final1 (0 = 1.5 x entry radius).
                                  # circuit: straight leg from the circle's tangent point to final1
    pattern: str = "legacy"       # "legacy" (centreline circles) or "circuit" (one-sided, see landing_items)
    side: int = -1                # circuit: -1 = pattern on the LEFT of the landing direction, +1 = right

    def to_dict(self):
        return asdict(self)


def _circuit_geometry(spec: "LandingSpec") -> dict:
    """One-sided circuit. Along = metres ahead of touchdown, lateral = metres right of the centreline.
    Hold and descent share ONE circle, tangent to the extended centreline at T, turning so that the aircraft
    moves in the landing direction at T (left side: counter-clockwise). Leaving it at T puts the aircraft on final.
    The last look flies the centreline from T over the approach and the strip; a forced 180 deg turn to the pattern
    side ("dw") and a downwind leg bring it back to the circle. A go-around climbs straight ahead and joins the
    same downwind turn."""
    g = approach_geometry(spec)
    # ArduPlane flies circles wider than commanded (L1 dynamics): COMMAND hold_radius_m, but place the circle and size
    # every turn with the radius actually FLOWN (turn_radius_m, measured), so the tangent exit lands on the centreline.
    R = max(spec.turn_radius_m, spec.hold_radius_m)
    s = -1 if spec.side < 0 else 1
    t_along = -(g["d_final1"] + spec.entry_lead_m)
    look_b = spec.hold_offset_m + spec.look_half_m
    return dict(R=R, s=s, t_along=t_along, c=(t_along, s * R), look_a=-g["d_final1"], look_b=look_b,
                dw=(look_b, s * 2 * R), signed_r=s * spec.hold_radius_m, **g)


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
    d_entry = d1 + (spec.entry_lead_m if spec.entry_lead_m > 0 else spec.entry_radius_m * 1.5)
    return dict(d_final1=d1, d_final2=d2, d_entry=d_entry, glide_rad=math.atan(g))


def landing_items(spec: LandingSpec) -> list[MissionItem]:
    if spec.pattern == "circuit":
        return _circuit_items(spec)
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


def _circuit_items(spec: LandingSpec) -> list[MissionItem]:
    g = _circuit_geometry(spec)
    td = spec.touchdown_rel_alt_m
    hold_alt = td + spec.hold_alt_m
    c_lat, c_lon = _along(spec, *g["c"])
    la = _along(spec, g["look_a"])
    lb = _along(spec, g["look_b"])
    dw = _along(spec, *g["dw"])
    f1 = _along(spec, -g["d_final1"])
    f2 = _along(spec, -g["d_final2"])
    ga = _along(spec, 200.0)
    C = mavlink
    return [
        MissionItem(C.MAV_CMD_NAV_LOITER_UNLIM, param3=g["signed_r"], lat=c_lat, lon=c_lon, alt=hold_alt, label="hold"),
        # LAST LOOK: straight, wings-level along the centreline at hold altitude, over the approach path and the strip
        MissionItem(C.MAV_CMD_NAV_WAYPOINT, lat=la[0], lon=la[1], alt=hold_alt, label="look_a"),
        MissionItem(C.MAV_CMD_NAV_WAYPOINT, lat=lb[0], lon=lb[1], alt=hold_alt, label="look_b"),
        # forced turn to the pattern side, then downwind back to the hold circle
        MissionItem(C.MAV_CMD_NAV_WAYPOINT, lat=dw[0], lon=dw[1], alt=hold_alt, label="dw"),
        MissionItem(C.MAV_CMD_DO_JUMP, frame=C.MAV_FRAME_GLOBAL, param1=0, param2=-1, label="jump_look"),
        # COMMIT: descend in the same circle, roll out at its tangent point onto final
        MissionItem(C.MAV_CMD_NAV_LOITER_TO_ALT, param2=g["signed_r"], lat=c_lat, lon=c_lon,
                    alt=td + spec.approach_alt_m, label="entry"),
        MissionItem(C.MAV_CMD_NAV_WAYPOINT, lat=f1[0], lon=f1[1], alt=td + spec.approach_alt_m, label="final1"),
        MissionItem(C.MAV_CMD_NAV_WAYPOINT, lat=f2[0], lon=f2[1], alt=td + spec.short_final_alt_m, label="final2"),
        MissionItem(C.MAV_CMD_NAV_LAND, param1=spec.abort_alt_m, lat=spec.touchdown_lat, lon=spec.touchdown_lon,
                    alt=td, label="touchdown"),
        MissionItem(C.MAV_CMD_NAV_CONTINUE_AND_CHANGE_ALT, param1=1, lat=ga[0], lon=ga[1],
                    alt=td + spec.goaround_alt_m, label="goaround"),
    ]


def with_jump_back(items: list[MissionItem], base_seq: int) -> list[MissionItem]:
    """Resolve DO_JUMP targets and append the post-go-around jump. base_seq = seq of items[0].
    Legacy: the go-around returns straight to the hold. Circuit: it joins the downwind turn ("dw") first."""
    idx = {it.label: i for i, it in enumerate(items)}
    for it in items:
        if it.label == "jump_look":
            it.param1 = base_seq + idx["hold"]
    target = idx.get("dw", idx["hold"])
    return items + [MissionItem(mavlink.MAV_CMD_DO_JUMP, frame=mavlink.MAV_FRAME_GLOBAL, param1=base_seq + target,
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


def _turnarounds(spec: LandingSpec, along_m: float, direction: float, alt: float, step_deg: float = 10.0):
    """180 deg reversal at `along_m` (metres ahead of touchdown on the strip axis) while travelling in `direction`
    (+1 = landing heading, -1 = opposite). Which way the plane turns depends on wind and L1, so BOTH
    semicircles are returned (left and right): conservative for clearance and the geofence."""
    r = spec.turn_radius_m
    out = []
    for side in (-1.0, 1.0):
        for k in range(int(180 / step_deg) + 1):
            a = math.radians(k * step_deg)
            fwd = r * math.sin(a) * direction
            lat_off = side * r * (1 - math.cos(a))
            out.append((*_along(spec, along_m + fwd, lat_off), alt))
    return out


def survey_items_fenced(lat0: float, lon0: float, width_m: float, length_m: float, heading_deg: float, alt_m: float,
                        spacing_m: float, turn_radius_m: float, fence_latlon: list | None = None, margin_m: float = 20.0,
                        lead_in_m: float = 50.0, min_line_m: float = 60.0) -> list[MissionItem]:
    """Survey lines like survey_items, but sized for the radius the aircraft actually FLIES and kept inside a fence.
    Every end turn is modelled as in survey_path_points: it bulges turn_radius_m past the line end and up to two turn
    radii sideways toward the next line. Line ends are pulled in until that whole turn stays margin_m inside the
    fence; lines left shorter than min_line_m are dropped. Consecutive lines are interleaved to alternate sides."""
    from shapely.geometry import LineString, Polygon

    from cloudbreak.common.geodesy import enu_offset

    n = max(1, int(math.ceil(width_m / spacing_m)) + 1)
    h = math.radians(heading_deg)
    ux, uy = math.sin(h), math.cos(h)
    vx, vy = math.cos(h), -math.sin(h)
    step = width_m / max(1, n - 1) if n > 1 else 0.0
    k = max(1, int(math.ceil(2 * turn_radius_m / step))) if step > 0 else 1
    k = min(k, max(1, n // 2))
    order = []
    for start in range(k):
        order += list(range(start, n, k))
    R = turn_radius_m
    half = length_m / 2 + lead_in_m
    offs = {i: (-width_m / 2 + i * step if n > 1 else 0.0) for i in range(n)}
    iv = {i: [-half, half] for i in order}                       # along-track interval of each line
    xy = lambda a, o: (a * ux + o * vx, a * uy + o * vy)         # noqa: E731
    if fence_latlon:
        poly = Polygon([enu_offset(lat0, lon0, la, lo) for la, lo in fence_latlon])
        inner = poly.buffer(-(margin_m + 1.0))                  # 1 m cushion: never exactly on the limit
        fwd = poly.buffer(-(margin_m + R + 1.0))
        for i in list(order):                                    # 1) along-track: end bulge (R) inside the fence
            seg = LineString([xy(-half, offs[i]), xy(half, offs[i])]).intersection(fwd)
            parts = [g for g in getattr(seg, "geoms", [seg]) if not g.is_empty]
            if not parts:
                iv.pop(i)
                continue
            g = max(parts, key=lambda q: q.length)
            al = sorted(px * ux + py * uy for px, py in g.coords)
            iv[i] = [al[0], al[-1]]

        def envelope_ok(a_end, sign_a, o_a, o_b):
            """turn from (a_end on line o_a, travelling sign_a) toward line o_b: forward R, sideways 2R"""
            side = 1.0 if o_b > o_a else -1.0
            corners = [xy(a_end + sign_a * f, o_a + side * lat) for f in (0.0, R) for lat in (0.0, 2 * R)]
            return inner.contains(Polygon([corners[0], corners[1], corners[3], corners[2]]))

        for _ in range(60):                                      # 2) sideways: shrink line pairs until turns fit
            seq = [i for i in order if i in iv and iv[i][1] - iv[i][0] >= min_line_m]
            changed = False
            for j in range(len(seq) - 1):
                a, b = seq[j], seq[j + 1]
                sign_a = 1.0 if j % 2 == 0 else -1.0             # line j flown + (even) or - (odd) along track
                a_end = iv[a][1] if sign_a > 0 else iv[a][0]
                b_start = iv[b][1] if sign_a > 0 else iv[b][0]      # the next line starts at the same end
                if not (envelope_ok(a_end, sign_a, offs[a], offs[b]) and envelope_ok(b_start, sign_a, offs[b], offs[a])):
                    if sign_a > 0:
                        iv[a][1] -= 10.0
                        iv[b][1] -= 10.0
                    else:
                        iv[a][0] += 10.0
                        iv[b][0] += 10.0
                    changed = True
            if not changed:
                break
    seq = [i for i in order if i in iv and iv[i][1] - iv[i][0] >= min_line_m]
    items = []
    for j, i in enumerate(seq):
        a, b = iv[i] if j % 2 == 0 else iv[i][::-1]
        for sv in (a, b):
            lat, lon = offset_latlon(lat0, lon0, *xy(sv, offs[i]))
            items.append(MissionItem(mavlink.MAV_CMD_NAV_WAYPOINT, lat=lat, lon=lon, alt=alt_m, label=f"survey_{i}"))
    return items


def survey_path_points(items: list[MissionItem], turn_radius_m: float, step_m: float = 5.0):
    """Lines plus every end turn: a semicircle of the flown radius from each line end toward the next line, and the
    mirror one into the next line's start (covers the overshoot when lines are closer than 2 turn radii)."""
    from cloudbreak.common.geodesy import enu_offset

    pts = path_points(items, 0, 0, step_m)
    wps = [it for it in items if it.command == mavlink.MAV_CMD_NAV_WAYPOINT]
    R = turn_radius_m
    for e_i in range(1, len(wps) - 1, 2):            # line ends: wps[1], wps[3], ...
        a0, a1, nxt = wps[e_i - 1], wps[e_i], wps[e_i + 1]
        de, dn = enu_offset(a0.lat, a0.lon, a1.lat, a1.lon)
        L = math.hypot(de, dn) or 1.0
        ux, uy = de / L, dn / L                      # line direction
        xe, xn = enu_offset(a1.lat, a1.lon, nxt.lat, nxt.lon)
        side = 1.0 if (xe * uy - xn * ux) > 0 else -1.0   # + = next line to the right
        rx, ry = uy * side, -ux * side               # unit toward the next line
        for base, sgn in ((a1, 1.0), (nxt, -1.0)):
            for k in range(19):
                th = math.radians(10 * k)
                f = R * math.sin(th)                 # forward (past the line end)
                lat_ = sgn * R * (1 - math.cos(th))  # toward the next line (mirrored at the next start)
                pts.append((*offset_latlon(base.lat, base.lon, f * ux + lat_ * rx, f * uy + lat_ * ry), base.alt))
    return pts


def landing_path_points(spec: LandingSpec, climb_gradient: float = 0.15, step_m: float = 5.0):
    """Flight path for clearance and geofence checks of a landing sequence:
      * hold circle; last-look leg look_a -> look_b, with the 180 deg reversal at each end (the plane arrives at
        look_a from the hold, and turns back to the hold after look_b);
      * entry circle -> final1 -> final2 -> touchdown;
      * the MISSED APPROACH from the decision point (final2), climbing at `climb_gradient` along the landing heading
        to max(abort, go-around) altitude, then the reversal and the leg back to the hold.
    (A go-around below the decision height is the pilot's call; the plan must not depend on it.)"""
    if spec.pattern == "circuit":
        return _circuit_path_points(spec, climb_gradient, step_m)
    items = landing_items(spec)
    by = {it.label: it for it in items}
    td = spec.touchdown_rel_alt_m
    hold_alt = td + spec.hold_alt_m
    pts = path_points([by["hold"], by["look_a"], by["look_b"], by["entry"], by["final1"], by["final2"], by["touchdown"]],
                      0, 0, step_m)
    pts += _turnarounds(spec, spec.hold_offset_m - spec.look_half_m, -1.0, hold_alt)
    pts += _turnarounds(spec, spec.hold_offset_m + spec.look_half_m, +1.0, hold_alt)
    f2 = by["final2"]
    geo = approach_geometry(spec)
    top = td + max(spec.goaround_alt_m, spec.abort_alt_m)
    s = 0.0
    while True:
        alt = f2.alt + climb_gradient * s
        lat, lon = _along(spec, -geo["d_final2"] + s)
        pts.append((lat, lon, min(alt, top)))
        if alt >= top or s > 800:
            break
        s += step_m
    ga_end = -geo["d_final2"] + s
    pts += _turnarounds(spec, ga_end, +1.0, top)
    # back to the hold at go-around altitude (conservative: the climb to hold altitude is not credited)
    hold_lat, hold_lon = by["hold"].lat, by["hold"].lon
    pts += path_points([MissionItem(mavlink.MAV_CMD_NAV_WAYPOINT, lat=_along(spec, ga_end)[0], lon=_along(spec, ga_end)[1], alt=top),
                        MissionItem(mavlink.MAV_CMD_NAV_WAYPOINT, lat=hold_lat, lon=hold_lon, alt=top)], 0, 0, step_m)
    return pts


def _circuit_path_points(spec: LandingSpec, climb_gradient: float, step_m: float):
    """Modelled flight path of the circuit, every leg and turn, each at its lowest altitude:
    hold/descent circle (checked at approach altitude: conservative), centreline look leg, the forced turn and
    downwind leg (at go-around altitude: a go-around also flies them), final, and the straight go-around climb."""
    g = _circuit_geometry(spec)
    R, s = g["R"], g["s"]
    td = spec.touchdown_rel_alt_m
    hold, appr = td + spec.hold_alt_m, td + spec.approach_alt_m
    top = td + max(spec.goaround_alt_m, spec.abort_alt_m)
    pts = []

    def seg(a0, l0, a1, l1, alt0, alt1):
        n = max(1, int(math.hypot(a1 - a0, l1 - l0) / step_m))
        for k in range(n + 1):
            f = k / n
            pts.append((*_along(spec, a0 + (a1 - a0) * f, l0 + (l1 - l0) * f), alt0 + (alt1 - alt0) * f))

    def turn(a_start, alt):
        """180 deg from (a_start, 0) heading forward to (a_start, 2Rs) heading back, bulging ahead by R."""
        for k in range(19):
            th = math.radians(10 * k)
            pts.append((*_along(spec, a_start + R * math.sin(th), s * R * (1 - math.cos(th))), alt))

    ca, cl = g["c"]
    for k in range(72):                                           # hold + descent circle
        th = 2 * math.pi * k / 72
        pts.append((*_along(spec, ca + R * math.sin(th), cl + R * math.cos(th)), appr))
    seg(g["t_along"], 0, g["look_b"], 0, hold, hold)              # last look along the centreline
    turn(g["look_b"], hold)
    seg(g["look_b"], 2 * s * R, ca, 2 * s * R, top, top)          # downwind back to the circle
    seg(g["t_along"], 0, -g["d_final1"], 0, appr, appr)           # roll-out onto final
    seg(-g["d_final1"], 0, -g["d_final2"], 0, appr, td + spec.short_final_alt_m)
    seg(-g["d_final2"], 0, 0.0, 0, td + spec.short_final_alt_m, td)
    s_m, f2a = 0.0, td + spec.short_final_alt_m                   # missed approach from the decision point
    while True:
        alt = min(f2a + climb_gradient * s_m, top)
        pts.append((*_along(spec, -g["d_final2"] + s_m), alt))
        if alt >= top or s_m > 800:
            break
        s_m += step_m
    turn(-g["d_final2"] + s_m, top)
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
