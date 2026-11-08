"""Landing-strip search and ranking (Free-LSD style, conservative, explainable).

1. landable mask = evidence-grid lower bound P(safe) >= tau AND enough views AND slope/roughness limits AND
   outside buffered hazards (grid hazards + prior hazards + wires/barriers)
2. rotate the mask to each axis heading, box-filter an L x W window -> every centre where a full strip fits
3. NMS, then evaluate both landing directions: wind components, approach-path clearance against the LiDAR
   DSM (same function the governor re-runs), evidence statistics, surface type
4. transparent weighted score; every candidate lists its constraints and the binding (least-slack) one

The same machinery on the *prior-permissive* mask (unknown allowed) nominates areas worth surveying.
"""
from __future__ import annotations

import json
import math
import tomllib
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np
from scipy import ndimage

from cloudbreak.common.classes import CLASSES, HAZARD_IDX, IDX, SAFE, SURFACE_PREF
from cloudbreak.common.clearance import load_terrain, path_clearance
from cloudbreak.common.config import site
from cloudbreak.common.fence import check_path, site_fence
from cloudbreak.common.config import CONFIG_DIR, data_dir
from cloudbreak.common.geodesy import utm_to_lonlat
from cloudbreak.common.missions import LandingSpec, landing_items, landing_path_points, path_points


def load_aircraft() -> dict:
    with open(CONFIG_DIR / "aircraft_tutor.toml", "rb") as f:
        cfg = tomllib.load(f)
    learned = data_dir() / "autoland" / "dispersion.json"
    if learned.exists():
        try:
            cfg["landing"].update({k: v for k, v in json.loads(learned.read_text()).items() if k in cfg["landing"]})
            cfg["landing"]["_learned"] = True
        except Exception:
            pass
    return cfg


def margins_from_cfg(cfg: dict) -> dict:
    L = cfg["landing"]
    return dict(enroute=L["clearance_enroute_m"], final=L["clearance_final_m"], exempt=40.0, taper=L["clearance_taper_m"])


def required_dims(cfg: dict) -> tuple[float, float]:
    L = cfg["landing"]
    length = 2 * L["touchdown_disp_long_m"] + L["rollout_m"]
    length = float(np.clip(length, L["min_length_m"], L["max_length_m"]))
    width = cfg["airframe"]["wingspan_m"] + 2 * L["touchdown_disp_lat_m"] + 2 * L["nav_sigma_m"]
    return length, width


def _rotate(img: np.ndarray, angle_deg: float, interp=cv2.INTER_NEAREST):
    h, w = img.shape
    c = (w / 2.0, h / 2.0)
    M = cv2.getRotationMatrix2D(c, angle_deg, 1.0)
    cs, sn = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sn + w * cs) + 2, int(h * cs + w * sn) + 2
    M[0, 2] += nw / 2.0 - c[0]
    M[1, 2] += nh / 2.0 - c[1]
    out = cv2.warpAffine(img, M, (nw, nh), flags=interp, borderValue=0)
    return out, M


@dataclass
class RawStrip:
    axis_deg: float
    cx: float            # UTM centre
    cy: float
    avail_len_m: float
    score_mean: float


def strip_search(mask: np.ndarray, score: np.ndarray, grid, L_m: float, W_m: float, step_deg: float = 10.0,
                 per_heading: int = 4, min_sep_m: float = 20.0, center_ok=None) -> list[RawStrip]:
    """`center_ok(angle)` (optional) returns a rotated mask of allowed strip centres (e.g. the geofence filter)."""
    res = grid.res
    Lp, Wp = max(3, int(round(L_m / res))), max(3, int(round(W_m / res)))
    out = []
    for ang in np.arange(0.0, 180.0, step_deg):
        m_r, M = _rotate(mask.astype(np.uint8), ang)
        s_r, _ = _rotate(score.astype(np.float32), ang, cv2.INTER_LINEAR)
        bad = (m_r == 0).astype(np.float32)
        cnt = cv2.boxFilter(bad, -1, (Wp, Lp), normalize=False, borderType=cv2.BORDER_CONSTANT)
        feas = cnt < 0.5
        if center_ok is not None:
            feas &= center_ok(float(ang))
        if not feas.any():
            continue
        smean = cv2.boxFilter(s_r, -1, (Wp, Lp), normalize=True, borderType=cv2.BORDER_CONSTANT)
        rowband = cv2.boxFilter(bad, -1, (Wp, 1), normalize=False, borderType=cv2.BORDER_CONSTANT) < 0.5
        ys, xs = np.nonzero(feas)
        order = np.argsort(-smean[ys, xs])
        Minv = cv2.invertAffineTransform(M)
        picked = []
        for i in order:
            y, x = ys[i], xs[i]
            if any((y - py) ** 2 + (x - px) ** 2 < (min_sep_m / res) ** 2 for py, px in picked):
                continue
            picked.append((y, x))
            col = rowband[:, x]
            up = y
            while up > 0 and col[up - 1]:
                up -= 1
            dn = y
            while dn < len(col) - 1 and col[dn + 1]:
                dn += 1
            ox, oy = Minv @ np.array([x, y, 1.0])
            cx, cy = grid.rc_to_xy(oy, ox)
            out.append(RawStrip(float(ang), float(cx), float(cy), float((dn - up + 1) * res), float(smean[y, x])))
            if len(picked) >= per_heading:
                break
    return out


@dataclass
class Candidate:
    id: str
    axis_deg: float
    heading_deg: float
    center_latlon: tuple
    touchdown_latlon: tuple
    threshold_latlon: tuple
    length_m: float
    width_m: float
    avail_len_m: float
    spec: dict
    metrics: dict
    constraints: list
    feasible: bool
    binding: str
    score: float
    terms: dict
    surface: str
    corners_latlon: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _strip_cells(grid, cx, cy, heading_deg, L, W):
    """(rows, cols) index arrays of grid cells inside the oriented strip rectangle (windowed, fast)."""
    rad = math.hypot(L, W) / 2 + grid.res
    r0, c0 = grid.xy_to_rc(cx - rad, cy + rad)
    r1, c1 = grid.xy_to_rc(cx + rad, cy - rad)
    r0, c0 = max(0, int(r0)), max(0, int(c0))
    r1, c1 = min(grid.height, int(r1) + 1), min(grid.width, int(c1) + 1)
    rr, cc = np.mgrid[r0:r1, c0:c1]
    X, Y = grid.rc_to_xy(rr, cc)
    h = math.radians(heading_deg)
    ux, uy = math.sin(h), math.cos(h)
    dx, dy = X - cx, Y - cy
    m = (np.abs(dx * ux + dy * uy) <= L / 2) & (np.abs(dx * uy - dy * ux) <= W / 2)
    return rr[m], cc[m]


def _corners(cx, cy, heading_deg, L, W):
    h = math.radians(heading_deg)
    ux, uy, vx, vy = math.sin(h), math.cos(h), math.cos(h), -math.sin(h)
    pts = []
    for a, b in ((-1, -1), (-1, 1), (1, 1), (1, -1)):
        x = cx + a * L / 2 * ux + b * W / 2 * vx
        y = cy + a * L / 2 * uy + b * W / 2 * vy
        lon, lat = utm_to_lonlat(x, y)
        pts.append((lat, lon))
    return pts


def make_spec(Lc: dict, L: float, td_lat: float, td_lon: float, direction: float, rel: float,
              side: int = -1) -> LandingSpec:
    """The landing pattern for a strip of length L (pattern sizes from the aircraft config [landing])."""
    return LandingSpec(touchdown_lat=round(td_lat, 7), touchdown_lon=round(td_lon, 7), heading_deg=round(direction, 1),
                       touchdown_rel_alt_m=round(rel, 2), hold_alt_m=Lc["hold_alt_m"],
                       hold_offset_m=round((0.5 - Lc["aim_fraction"]) * L, 1), approach_alt_m=Lc["approach_alt_m"],
                       glide_slope_pct=Lc["glide_slope_pct"], short_final_alt_m=min(8.0, Lc["approach_alt_m"] / 2),
                       entry_radius_m=Lc.get("entry_radius_m", 35.0), hold_radius_m=Lc.get("hold_radius_m", 40.0),
                       goaround_alt_m=Lc.get("goaround_alt_m", 40.0), abort_alt_m=Lc.get("abort_alt_m", 30.0),
                       look_half_m=round(L / 2 + Lc.get("look_margin_m", 85.0), 1),
                       turn_radius_m=Lc.get("turn_radius_m", 35.0), entry_lead_m=Lc.get("entry_lead_m", 0.0),
                       pattern=Lc.get("pattern", "legacy"), side=side)


def pattern_extents(Lc: dict, L: float) -> tuple[float, float, float, float]:
    """(behind, ahead, lat_pattern_side, lat_other_side) metres of the full modelled pattern relative to the STRIP
    CENTRE, for a strip flown in its landing direction with the pattern on its left. Computed from the same path
    model the clearance/fence checks use. Mirror lateral values for a right-hand pattern."""
    from cloudbreak.common.geodesy import enu_offset

    lat0, lon0 = 42.7, -73.7
    spec = make_spec(Lc, L, lat0, lon0, 0.0, 0.0, side=-1)   # heading 0: along = north, lateral = east (+ = right)
    pts = landing_path_points(spec, Lc["missed_climb_gradient"])
    off = [enu_offset(lat0, lon0, la, lo) for la, lo, _ in pts]
    along = np.array([dn for _, dn in off]) - spec.hold_offset_m      # hold_offset = centre - touchdown
    lateral = np.array([de for de, _ in off])
    return float(-along.min()), float(along.max()), float(max(0.0, -lateral.min())), float(max(0.0, lateral.max()))


def fence_center_filter(grid, fence, Lc: dict, L: float):
    """Callable(angle) -> rotated bool mask of strip centres where the whole pattern stays >= fence.path_margin_m
    inside the fence for at least one of the four (landing direction x pattern side) choices."""
    poly = fence.utm_polygon()
    xs, ys = poly.exterior.xy
    r, c = grid.xy_to_rc(np.array(xs), np.array(ys))
    inside = np.zeros(grid.shape, np.uint8)
    cv2.fillPoly(inside, [np.round(np.stack([c, r], 1)).astype(np.int32)], 1)
    dist = cv2.distanceTransform(inside, cv2.DIST_L2, 5) * grid.res
    ok = (dist >= fence.path_margin_m).astype(np.float32)
    behind, ahead, lat_p, lat_o = pattern_extents(Lc, L)
    res = grid.res
    b, a = int(math.ceil(behind / res)), int(math.ceil(ahead / res))
    wp, wo = int(math.ceil(lat_p / res)), int(math.ceil(lat_o / res))
    ksize = (wp + wo + 1, b + a + 1)
    full = float(ksize[0] * ksize[1])

    def center_ok(ang: float) -> np.ndarray:
        rot, _ = _rotate(ok, ang, cv2.INTER_NEAREST)
        out = np.zeros(rot.shape, bool)
        for anchor_y in (b, a):            # landing direction along the rotated strip axis
            for anchor_x in (wp, wo):      # pattern side
                cnt = cv2.boxFilter(rot, -1, ksize, anchor=(anchor_x, anchor_y), normalize=False,
                                    borderType=cv2.BORDER_CONSTANT)
                out |= cnt >= full - 0.5
        return out

    return center_ok


def evaluate(raw: RawStrip, idx: int, ctx: dict) -> list[Candidate]:
    cfg, layers, ev = ctx["cfg"], ctx["layers"], ctx["ev"]
    Lc = cfg["landing"]
    L, W = ctx["L"], ctx["W"]
    grid = layers.grid
    cells = _strip_cells(grid, raw.cx, raw.cy, raw.axis_deg, L, W)
    plb, vac = ctx["p_lb"][cells], ctx["vac"][cells]
    slope = layers.slope[cells]
    rough = ctx["rough"][cells]
    cm = ctx["class_map"][cells]
    safe_counts = {c: int((cm == IDX[c]).sum()) for c in SAFE}
    surface = max(safe_counts, key=safe_counts.get) if sum(safe_counts.values()) else "unknown"
    wind = ctx["wind"]
    home_lat, home_lon = ctx["home"]
    out = []
    for direction in (raw.axis_deg, (raw.axis_deg + 180.0) % 360.0):
        h = math.radians(direction)
        ux, uy = math.sin(h), math.cos(h)
        thx, thy = raw.cx - L / 2 * ux, raw.cy - L / 2 * uy
        tdx, tdy = thx + Lc["aim_fraction"] * L * ux, thy + Lc["aim_fraction"] * L * uy
        td_lon, td_lat = utm_to_lonlat(tdx, tdy)
        th_lon, th_lat = utm_to_lonlat(thx, thy)
        c_lon, c_lat = utm_to_lonlat(raw.cx, raw.cy)
        terrain = ctx["terrain"]
        dtm_td, _ = terrain.sample(np.array([td_lat]), np.array([td_lon]))
        dtm_home, _ = terrain.sample(np.array([home_lat]), np.array([home_lon]))
        rel = float(dtm_td[0] - dtm_home[0]) + ctx.get("baro_bias_m", 0.0)
        # circuit patterns can sit on either side of the strip: keep the side that is feasible / has more room
        best = None
        for side in ((-1, 1) if Lc.get("pattern", "legacy") == "circuit" else (-1,)):
            sp = make_spec(Lc, L, td_lat, td_lon, direction, rel, side=side)
            pth = landing_path_points(sp, Lc["missed_climb_gradient"])
            cl = path_clearance(pth, home_lat, home_lon, td_lat, td_lon, terrain, margins_from_cfg(cfg))
            fe = check_path(pth, ctx["fence"]) if ctx.get("fence") is not None else None
            key = (bool(cl.ok and (fe is None or fe.ok)), min(cl.worst_margin_m if math.isfinite(cl.worst_margin_m) else -99,
                                                              (fe.worst_margin_m - ctx["fence"].path_margin_m) if fe else 99))
            if best is None or key > best[0]:
                best = (key, sp, pth, cl, fe)
        _, spec, path, clr, fen = best
        rel_dir = math.radians(wind["from_deg"] - direction)
        headwind = wind["speed"] * math.cos(rel_dir)
        crosswind = abs(wind["speed"] * math.sin(rel_dir))
        dist_home = _dist_m(home_lat, home_lon, c_lat, c_lon)
        cons = [
            dict(name="p_safe_lower_bound_min", value=round(float(plb.min()), 3), limit=Lc.get("p_safe_cell_min", Lc["p_safe_min"]),
                 ok=bool(plb.min() >= Lc.get("p_safe_cell_min", Lc["p_safe_min"])),
                 slack=float(plb.min() - Lc.get("p_safe_cell_min", Lc["p_safe_min"])) / Lc.get("p_safe_cell_min", Lc["p_safe_min"])),
            dict(name="p_safe_lower_bound_strip_mean", value=round(float(plb.mean()), 3), limit=Lc["p_safe_min"],
                 ok=bool(plb.mean() >= Lc["p_safe_min"]), slack=float(plb.mean() - Lc["p_safe_min"]) / Lc["p_safe_min"]),
            dict(name="unknown_fraction", value=round(float((vac > Lc["vacuity_max"]).mean()), 3), limit=0.0,
                 ok=bool((vac <= Lc["vacuity_max"]).all()), slack=-float((vac > Lc["vacuity_max"]).mean())),
            dict(name="slope_max_deg", value=round(float(np.nanmax(slope)), 2), limit=Lc["slope_max_deg"],
                 ok=bool(np.nanmax(slope) <= Lc["slope_max_deg"]), slack=float(Lc["slope_max_deg"] - np.nanmax(slope)) / Lc["slope_max_deg"]),
            dict(name="roughness_max_m", value=round(float(np.nanmax(rough)), 3), limit=Lc["roughness_max_m"],
                 ok=bool(np.nanmax(rough) <= Lc["roughness_max_m"]), slack=float(Lc["roughness_max_m"] - np.nanmax(rough)) / Lc["roughness_max_m"]),
            dict(name="approach_clearance_m", value=round(clr.worst_margin_m, 1) if math.isfinite(clr.worst_margin_m) else None,
                 limit=0.0, ok=clr.ok, slack=(clr.worst_margin_m / 10.0) if math.isfinite(clr.worst_margin_m) else -1.0, detail=clr.reason),
            dict(name="crosswind_mps", value=round(crosswind, 1), limit=5.0, ok=crosswind <= 5.0, slack=(5.0 - crosswind) / 5.0),
            dict(name="tailwind_mps", value=round(max(0.0, -headwind), 1), limit=1.5, ok=-headwind <= 1.5, slack=(1.5 + headwind) / 1.5),
        ]
        need = L + Lc.get("overrun_margin_m", 0.0)      # open ground past the strip for a long float / rollout
        cons.append(dict(name="open_length_m", value=round(raw.avail_len_m, 1), limit=round(need, 1),
                         ok=bool(raw.avail_len_m >= need), slack=float(raw.avail_len_m - need) / max(need, 1.0)))
        if fen is not None:
            lim = ctx["fence"].path_margin_m
            cons.append(dict(name="geofence_margin_m", value=round(fen.worst_margin_m, 1), limit=lim, ok=fen.ok,
                             slack=(fen.worst_margin_m - lim) / lim, detail=fen.reason))
        feasible = all(c["ok"] for c in cons)
        binding = min(cons, key=lambda c: c["slack"])
        len_margin = max(0.0, raw.avail_len_m - L)
        terms = dict(
            headwind=0.30 * float(np.clip(headwind / 5.0, -1, 1)),
            length_margin=0.20 * float(np.clip(len_margin / 40.0, 0, 1)),
            clearance=0.20 * float(np.clip((clr.worst_margin_m if math.isfinite(clr.worst_margin_m) else -10) / 10.0, -1, 1)),
            evidence=0.15 * float(np.clip((plb.mean() - Lc["p_safe_min"]) / (1 - Lc["p_safe_min"]), -1, 1)),
            surface=0.10 * SURFACE_PREF.get(surface, 0.0),
            proximity=0.05 * float(np.clip(1 - dist_home / 600.0, 0, 1)),
        )
        cid = f"C{idx:02d}{'a' if direction == raw.axis_deg else 'b'}"
        out.append(Candidate(
            id=cid, axis_deg=raw.axis_deg, heading_deg=round(direction, 1), center_latlon=(c_lat, c_lon),
            touchdown_latlon=(td_lat, td_lon), threshold_latlon=(th_lat, th_lon), length_m=round(L, 1), width_m=round(W, 1),
            avail_len_m=round(raw.avail_len_m, 1), spec=spec.to_dict(),
            metrics=dict(p_lb_mean=round(float(plb.mean()), 3), p_lb_min=round(float(plb.min()), 3),
                         views_min=int(ctx["views"][cells].min()), headwind_mps=round(headwind, 1),
                         crosswind_mps=round(crosswind, 1), clearance_m=round(clr.worst_margin_m, 1) if math.isfinite(clr.worst_margin_m) else None,
                         dist_home_m=round(dist_home), surface_counts=safe_counts),
            constraints=cons, feasible=feasible, binding=f"{binding['name']}={binding['value']} (limit {binding['limit']})",
            score=round(sum(terms.values()), 3) if feasible else round(sum(terms.values()) - 1.0, 3), terms={k: round(v, 3) for k, v in terms.items()},
            surface=surface, corners_latlon=_corners(raw.cx, raw.cy, direction, L, W)))
    return out


def _dist_m(lat1, lon1, lat2, lon2):
    from cloudbreak.common.geodesy import enu_offset

    de, dn = enu_offset(lat1, lon1, lat2, lon2)
    return math.hypot(de, dn)


def roughness_map(layers) -> np.ndarray:
    """Object height proxy from lidar: 90th percentile of height-above-ground in a 1.5 m window.
    (Max is dominated by QL2 noise/grass, ~0.1-0.15 m; objects >= ~0.3 m -- benches, goals, curbs -- still show.)
    NaN (no lidar) -> 9.9 so uncovered ground is never 'smooth'."""
    hag = np.nan_to_num(layers.hag, nan=9.9)
    return ndimage.percentile_filter(hag, 90, size=3).astype(np.float32)


_ROUGH_CACHE: dict = {}
_NOM_CACHE: dict = {}


def survey_nominations(layers, cfg, rough, buf) -> list:
    """Where could a strip fit if the unobserved ground turned out fine? PRIOR-ONLY and cached, so the list
    (and its indices) stays stable while the evidence grid changes."""
    key = id(layers)
    if key in _NOM_CACHE:
        return _NOM_CACHE[key]
    Lc = cfg["landing"]
    L, W = required_dims(cfg)
    prior_haz = np.isin(layers.prior_class, HAZARD_IDX) | (layers.osm_power > 0) | (layers.osm_barrier > 0)
    haz = ndimage.binary_dilation(prior_haz, iterations=max(1, int(buf / layers.grid.res)))
    permissive = ~haz & (layers.slope <= Lc["slope_max_deg"]) & (rough <= Lc["roughness_max_m"])         & ~np.isin(layers.prior_class, (IDX["tree"], IDX["building"], IDX["water"], IDX["tall_veg"]))
    nom = strip_search(permissive, np.isin(layers.prior_class, (IDX["short_grass"],)).astype(np.float32), layers.grid, L, W,
                       step_deg=15.0, per_heading=3, min_sep_m=25.0)
    # one entry per distinct area (largest open length), sorted by open length
    nom.sort(key=lambda r: -r.avail_len_m)
    picked = []
    for r in nom:
        if all(math.hypot(r.cx - q.cx, r.cy - q.cy) > 60 for q in picked):
            picked.append(r)
    out = []
    for r in picked[:6]:
        lon, lat = utm_to_lonlat(r.cx, r.cy)
        out.append(dict(center_latlon=(lat, lon), axis_deg=r.axis_deg, avail_len_m=round(r.avail_len_m, 1),
                        grass_frac=round(r.score_mean, 2), corners_latlon=_corners(r.cx, r.cy, r.axis_deg, L, W)))
    _NOM_CACHE[key] = out
    return out


def plan(ev, layers, wind: dict, home: tuple, cfg: dict | None = None, baro_bias_m: float = 0.0,
         max_eval: int = 14, step_deg: float = 15.0, per_heading: int = 3) -> dict:
    cfg = cfg or load_aircraft()
    Lc = cfg["landing"]
    L, W = required_dims(cfg)
    p_lb = ev.p_safe_lb()
    vac = ev.vacuity()
    rough = _ROUGH_CACHE.get(id(layers))
    if rough is None:
        rough = _ROUGH_CACHE.setdefault(id(layers), roughness_map(layers))
    buf = Lc.get("hazard_buffer_m", 1.0)   # strip width already holds wingspan + lateral dispersion + 2 sigma nav; this is map geolocation error only
    prior_haz = np.isin(layers.prior_class, HAZARD_IDX) | (layers.osm_power > 0) | (layers.osm_barrier > 0)
    haz = ev.hazard_mask(buffer_m=buf) | ndimage.binary_dilation(prior_haz, iterations=max(1, int(buf / layers.grid.res)))
    landable = (p_lb >= Lc.get("p_safe_cell_min", Lc["p_safe_min"])) & (vac <= Lc["vacuity_max"]) & (layers.slope <= Lc["slope_max_deg"]) \
        & (rough <= Lc["roughness_max_m"]) & ~haz
    ctx = dict(cfg=cfg, layers=layers, ev=ev, L=L, W=W, p_lb=p_lb, vac=vac, rough=rough, class_map=ev.class_map(),
               views=ev.views, wind=wind, home=home, terrain=load_terrain(), baro_bias_m=baro_bias_m,
               fence=site_fence(site()))
    center_ok = fence_center_filter(layers.grid, ctx["fence"], Lc, L) if ctx["fence"] is not None else None
    raws = strip_search(landable, p_lb, layers.grid, L, W, step_deg=step_deg, per_heading=per_heading, center_ok=center_ok)
    raws.sort(key=lambda r: -r.score_mean)
    cands = []
    for i, r in enumerate(raws[:max_eval]):
        cands += evaluate(r, i, ctx)
    cands.sort(key=lambda c: (-int(c.feasible), -c.score))
    noms = survey_nominations(layers, cfg, rough, buf)
    return dict(grid_version=ev.version, required_length_m=round(L, 1), required_width_m=round(W, 1),
                landable_cells=int(landable.sum()), candidates=[c.to_dict() for c in cands[:20]], survey_nominations=noms,
                wind=wind, learned_dispersion=bool(cfg["landing"].get("_learned")))
