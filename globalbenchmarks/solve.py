"""Solve the benchmarks: find landing strips on every scraped site with the planner's own strip search.

    .venv\\Scripts\\python -m globalbenchmarks.solve [--only ID[,ID]] [--category urban,...] [--strip L W]

Strip size comes from config/aircraft_tutor.toml (planner's required_dims, ~51 x 16 m); a strip also wants
`overrun_margin_m` of open ground beyond it (the planner's open_length constraint). Two runs per site, both through
cloudbreak.ground.core.planner.strips.strip_search on a 1 m local grid:

  camera  what a straight-down camera alone supports: colour/texture classes from the image + terrain slope.
  fused   camera + OSM priors mapped like core's build_prior: buildings, masts/poles/lamps, water, woods, power
          lines and barriers are hazards; roads and parking are pavement and pitches short grass (only where the
          image doesn't show a hazard). This is the answer a planner would act on.

OSM is also the reference for the camera run: a camera strip overlapping an OSM building / water / wood / power /
barrier feature is a "conflict" (likely false positive); a strip mostly on an OSM pitch is a "pitch hit".

Per site -> images/<category>/<id>/benchmark.jpg (left: imagery + fused strips; right: what the solver saw),
classes.png (class ids, cloudbreak.common.classes), result.json. Plus images/_sheets/benchmark_<category>.jpg,
images/_sheets/benchmark_all.jpg, images/results.json and RESULTS.md.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage

from cloudbreak.common.classes import CLASSES, COLORS, HAZARD_IDX, IDX, SAFE, SAFE_IDX, SURFACE_PREF
from cloudbreak.common.geodesy import Grid, offset_latlon
from cloudbreak.ground.core.planner.strips import load_aircraft, required_dims, strip_search
from globalbenchmarks.fetch import ROOT, load_dem, merc, put_text, site_dir
from globalbenchmarks.sites import CATEGORIES, SITES, Site, select

HERE = Path(__file__).resolve().parent
# copied from cloudbreak/ground/core/priors/build_layers.py (importing it creates C:\cb-data\priors folders)
HIGHWAY_HALF_WIDTH = {"motorway": 8, "trunk": 7, "primary": 6, "secondary": 5, "tertiary": 4.5, "residential": 4,
                      "unclassified": 4, "service": 3, "footway": 1.2, "path": 1.0, "cycleway": 1.2, "steps": 1.2,
                      "pedestrian": 3, "living_street": 3.5, "track": 2}
OSM_HAZ_LAYERS = ("building", "vertical", "water", "tree", "power", "barrier")
SEARCH_RES_M = 1.0
MAX_STRIPS = 5
HEAD_PX = 120                     # header height: location / strips found + full overrun / source
TITLE_PX = 44                     # panel title bar: "JEV9 Decision" (or "Planner Decision") / "Recognition Result"


def log(*a):
    print("[globalbenchmarks.solve]", *a, flush=True)


# ------------------------------------------------------------------ camera classes (single nadir RGB image)
def box_mean(a: np.ndarray, k: int) -> np.ndarray:
    return cv2.blur(a.astype(np.float32), (k, k), borderType=cv2.BORDER_REFLECT)


def local_std(gray: np.ndarray, k: int) -> np.ndarray:
    g = gray.astype(np.float32)
    m = box_mean(g, k)
    return np.sqrt(np.maximum(box_mean(g * g, k) - m * m, 0.0))


def _odd(n: float) -> int:
    return max(3, int(round(n)) | 1)


def camera_labels(bgr: np.ndarray, gsd_m: float) -> tuple[np.ndarray, np.ndarray, dict]:
    """Colour + texture rules in the Cloudbreak ontology -> (labels, shadow fraction, info).

    No height from one image: a flat roof can look like pavement and a crop like grass. Shadows are 'unknown'
    (they hide whatever is in them), never landable. Tuned on sampled patches (README, "Camera classes"):
      vegetation texture is measured after a ~2.5 m median, which removes painted pitch lines but not tree crowns;
      canopy also has dark gaps between crowns (shadow fraction in a ~7.5 m window), turf and lawns don't.
    """
    f = bgr.astype(np.float32)
    b, g, r = (box_mean(f[..., i], 3) for i in range(3))
    exg = (2 * g - r - b) / (r + g + b + 1e-3)                         # excess green
    hsv = cv2.cvtColor(cv2.blur(bgr, (3, 3)), cv2.COLOR_BGR2HSV).astype(np.float32)
    sat, val = hsv[..., 1], hsv[..., 2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    k = _odd(4.0 / gsd_m)                                             # ~4 m texture window
    sd = local_std(gray, k)                                           # raw texture (non-vegetation surfaces)
    tex = local_std(cv2.medianBlur(gray, _odd(2.5 / gsd_m)), k)       # texture without thin lines (vegetation)
    dark = box_mean((cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[..., 2] < 60).astype(np.float32), _odd(7.5 / gsd_m))
    shadow = val < 55
    veg = (exg > 0.035) & ~shadow
    tree = veg & ((tex > 12.0) | ((tex > 6.5) & (dark > 0.04)))
    water = (b > r + 8) & (b >= g - 2) & (val < 120) & (sd < 7) & ~veg
    grey = (sat < 38) & ~veg
    smooth = sd < 12.0
    lab = np.full(bgr.shape[:2], IDX["unknown"], np.uint8)
    lab[~veg & ~smooth] = IDX["rough"]
    lab[~veg & smooth] = IDX["dirt"]
    lab[grey & smooth & (val >= 60) & (val <= 235)] = IDX["pavement"]
    lab[veg & ~tree] = IDX["short_grass"]
    lab[tree] = IDX["tree"]
    lab[water] = IDX["water"]
    lab[shadow] = IDX["unknown"]          # deep shadow can't be told from water (canyon walls did); OSM supplies water
    lab[(val > 245) & (sat < 25)] = IDX["unknown"]                     # blown-out highlights: no texture to judge
    return lab, dark, dict(texture_window_px=k)


# ------------------------------------------------------------------ terrain
def slope_deg(dem: np.ndarray, res_m: float, terrain_src: str) -> np.ndarray:
    """Like core's build_dtm (light Gaussian, gradient), but smoothed to the source DEM's real resolution:
    1-10 m 3DEP vs ~10-30 m global tiles (unsmoothed upsampled SRTM steps read as fake slopes)."""
    sigma_m = 2.0 if terrain_src == "3dep" else 12.0
    sm = ndimage.gaussian_filter(dem.astype(np.float64), sigma_m / res_m)
    gy, gx = np.gradient(sm, res_m)
    return np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)


# ------------------------------------------------------------------ OSM -> rasters (mirrors core's build_osm)
def _rings_from_members(members: list) -> list[list[tuple]]:
    """Outer members of a multipolygon -> closed rings (members are often partial ways; join them end to end)."""
    segs = [[(p["lon"], p["lat"]) for p in m["geometry"]] for m in members
            if m.get("role") == "outer" and m.get("geometry")]
    rings = []
    while segs:
        ring = segs.pop(0)
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring += s[1:]
                elif s[-1] == ring[-1]:
                    ring += s[::-1][1:]
                elif s[-1] == ring[0]:
                    ring = s[:-1] + ring
                elif s[0] == ring[0]:
                    ring = s[::-1][:-1] + ring
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def osm_layers(osm: dict, meta: dict, shape: tuple) -> tuple[dict, list]:
    H, W = shape
    bb = meta["bbox_3857"]
    gsd = meta["gsd_m"]
    sx, sy = W / (bb[2] - bb[0]), H / (bb[3] - bb[1])
    SH = 2                                                           # cv2 sub-pixel bits

    def px(coords):
        out = []
        for lon, lat in coords:
            mx, my = merc(lat, lon)
            out.append(((mx - bb[0]) * sx * (1 << SH), (bb[3] - my) * sy * (1 << SH)))
        return np.round(np.array(out)).astype(np.int32)

    L = {k: np.zeros(shape, np.uint8) for k in ("building", "water", "tree", "pitch", "pavement", "road", "barrier",
                                                 "power", "vertical")}
    pitches = []
    pitch_id = np.zeros(shape, np.int32)       # which leisure=pitch polygon each pixel is on (0 = none)

    def fill(layer, rings):
        for ring in rings:
            cv2.fillPoly(L[layer], [px(ring)], 1, cv2.LINE_8, SH)

    def line(layer, coords, half_w_m, closed=False):
        t = max(1, int(round(2 * half_w_m / gsd)))
        cv2.polylines(L[layer], [px(coords)], closed, 1, t, cv2.LINE_8, SH)

    def disc(layer, lon, lat, r_m):
        c = px([(lon, lat)])[0]
        cv2.circle(L[layer], (int(c[0]), int(c[1])), max(1, int(round(r_m / gsd * (1 << SH)))), 1, -1, cv2.LINE_8, SH)

    for el in osm.get("elements", []):
        tags = el.get("tags", {})
        t = el["type"]
        rings, coords, point = [], None, None
        if t == "node":
            point = (el["lon"], el["lat"])
        elif t == "way" and el.get("geometry"):
            coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
            if len(coords) >= 4 and coords[0] == coords[-1]:
                rings = [coords]
        elif t == "relation" and el.get("members"):
            rings = _rings_from_members(el["members"])
        is_area = bool(rings)
        is_line = coords is not None and not is_area
        if "building" in tags and is_area:
            fill("building", rings)
        if tags.get("natural") == "water" or "waterway" in tags:
            if is_area:
                fill("water", rings)
            elif is_line:
                line("water", coords, 2.0)
        if tags.get("natural") in ("wood", "tree_row", "scrub") or tags.get("landuse") == "forest":
            if is_area:
                fill("tree", rings)
            elif is_line:
                line("tree", coords, 3.0)
        if tags.get("natural") == "tree" and point:
            disc("tree", *point, 4.0)
        if tags.get("leisure") in ("pitch", "track", "stadium") and is_area:
            fill("pitch", rings)
            if tags.get("leisure") == "pitch":
                pitches.append(dict(id=f"{t}/{el['id']}", sport=tags.get("sport"), name=tags.get("name"), rings=rings))
                for ring in rings:
                    cv2.fillPoly(pitch_id, [px(ring)], len(pitches), cv2.LINE_8, SH)
        if tags.get("amenity") == "parking" and is_area:
            fill("pavement", rings)
        hw = tags.get("highway")
        if hw and is_line:
            line("road", coords, HIGHWAY_HALF_WIDTH.get(hw, 3.0))
        if hw and is_area and tags.get("area") == "yes":
            fill("pavement", rings)
        if "barrier" in tags and (is_line or is_area):
            line("barrier", coords if is_line else rings[0], 1.0, closed=is_area)
        pw = tags.get("power")
        if pw in ("line", "minor_line", "cable") and is_line:
            line("power", coords, 30.0 if pw == "line" else 15.0)
        if pw in ("tower", "pole", "portal") or tags.get("man_made") in ("mast", "tower", "flagpole", "antenna", "chimney") \
                or hw == "street_lamp":
            if point is None and coords:
                point = tuple(np.mean(np.array(coords), axis=0))
            if point:
                disc("vertical", *point, 10.0 if pw == "tower" or tags.get("man_made") in ("mast", "tower") else 4.0)
    out = {k: v.astype(bool) for k, v in L.items()}
    out["pitch_id"] = pitch_id
    return out, pitches


def fuse(cam: np.ndarray, dark: np.ndarray, osm: dict) -> np.ndarray:
    """Core's build_prior priority without LiDAR: mapped hazards win, the image's own hazards stay hazards, and the
    OSM 'surface' hints (road/parking -> pavement) only fill pixels the image doesn't object to.
    Pitches are the exception: painted lines, numbers and logos read as texture, so inside an OSM pitch / track
    the camera's texture classes become short grass unless the image shows shadow (core's 'hag < 0.3' test needs
    LiDAR; shadow is the single-image stand-in for 'something tall here')."""
    lab = cam.copy()
    soft = np.isin(cam, SAFE_IDX) | (cam == IDX["unknown"])
    painted = np.isin(cam, (IDX["tree"], IDX["rough"], IDX["dirt"])) & (dark < 0.02)
    lab[osm["pitch"] & (soft | painted) & (cam != IDX["unknown"])] = IDX["short_grass"]
    lab[(osm["road"] | osm["pavement"]) & soft] = IDX["pavement"]
    lab[osm["tree"]] = IDX["tree"]
    lab[osm["water"]] = IDX["water"]
    lab[osm["vertical"] | osm["power"] | osm["barrier"]] = IDX["pole_wire"]
    lab[osm["building"]] = IDX["building"]
    return lab


# ------------------------------------------------------------------ strips
def landable_mask(lab: np.ndarray, slope05: np.ndarray, gsd: float, buffer_m: float, slope_max: float) -> np.ndarray:
    haz = ndimage.binary_dilation(np.isin(lab, HAZARD_IDX), iterations=max(1, int(round(buffer_m / gsd))))
    return np.isin(lab, SAFE_IDX) & (slope05 <= slope_max) & ~haz


def surface_score(lab: np.ndarray, slope05: np.ndarray, slope_max: float) -> np.ndarray:
    pref = np.zeros(len(CLASSES), np.float32)
    for c in SAFE:
        pref[IDX[c]] = SURFACE_PREF[c]
    return pref[lab] * (1.0 - 0.5 * np.clip(slope05 / slope_max, 0, 1))


def search(landable: np.ndarray, score: np.ndarray, gsd: float, extent: float, L: float, W: float, need: float,
           pitch_id: np.ndarray | None = None) -> list:
    """Strips via the planner's strip_search, then ranked (full overrun first) and thinned: at most one strip per
    mapped pitch (`pitch_id`, 0.5 m raster of OSM pitch numbers), and centres at least 0.75 L x (tile / 600 m) apart."""
    f = int(round(SEARCH_RES_M / gsd))
    n = landable.shape[0] // f
    land1 = cv2.resize(landable.astype(np.float32), (n, n), interpolation=cv2.INTER_AREA) >= 0.999   # every sub-cell
    sc1 = cv2.resize(score, (n, n), interpolation=cv2.INTER_AREA)
    if not land1.any():
        return []
    grid = Grid(-extent / 2, extent / 2, SEARCH_RES_M, n, n, crs="local ENU (m), site at (0, 0)")
    # bigger tiles get more, more spread-out candidates per heading: on a 1.5 km campus the top 3 per heading all
    # landed on the flattest fields and '86 Field never got a look. 600 m tiles keep exactly (3, L/2, MAX_STRIPS).
    k = max(1.0, extent / 600.0)
    raws = strip_search(land1, sc1, grid, L, W, step_deg=15.0, per_heading=int(math.ceil(3 * k * k)),
                        min_sep_m=max(L / 2, 10.0) * k)
    # like the planner's ranking: strips that pass the open-length (overrun) constraint first, then surface score
    raws.sort(key=lambda r: (-int(r.avail_len_m >= need), -round(r.score_mean, 2), -r.avail_len_m))
    out, used = [], set()
    for r in raws:
        pid = strip_pitch(r, pitch_id, L, W, extent, gsd) if pitch_id is not None else 0
        if pid and pid in used:
            continue
        if any(math.hypot(r.cx - q.cx, r.cy - q.cy) < L * 0.75 * k for q in out):   # ~one per field on big tiles
            continue
        out.append(r)
        used.add(pid)
        if len(out) >= int(round(MAX_STRIPS * k * k)):
            break
    return out


def strip_pitch(r, pitch_id: np.ndarray, L: float, W: float, extent: float, gsd: float) -> int:
    """The mapped pitch (1-based id) covering most of the strip, 0 if under half of it is on one."""
    m = np.zeros(pitch_id.shape, np.uint8)
    cv2.fillPoly(m, [np.round(strip_poly_px(r, L, W, extent, gsd) * 4).astype(np.int32)], 1, cv2.LINE_8, 2)
    ids = pitch_id[m.astype(bool)]
    if not ids.size:
        return 0
    counts = np.bincount(ids)
    best = int(counts[1:].argmax()) + 1 if counts.size > 1 else 0
    return best if best and counts[best] >= 0.5 * ids.size else 0


def strip_poly_px(r, L: float, W: float, extent: float, gsd: float) -> np.ndarray:
    a = math.radians(r.axis_deg)
    u = np.array([math.sin(a), math.cos(a)])
    v = np.array([math.cos(a), -math.sin(a)])
    c = np.array([r.cx, r.cy])
    g = np.array([c - L / 2 * u - W / 2 * v, c - L / 2 * u + W / 2 * v, c + L / 2 * u + W / 2 * v, c + L / 2 * u - W / 2 * v])
    return np.stack([(g[:, 0] + extent / 2) / gsd, (extent / 2 - g[:, 1]) / gsd], 1).astype(np.float32)


def describe(r, rank: int, lab: np.ndarray, slope05: np.ndarray, osm: dict, pitches: list, meta: dict, L: float, W: float,
             need: float) -> dict:
    ext, gsd = meta["extent_m"], meta["gsd_m"]
    poly = strip_poly_px(r, L, W, ext, gsd)
    m = np.zeros(lab.shape, np.uint8)
    cv2.fillPoly(m, [np.round(poly * 4).astype(np.int32)], 1, cv2.LINE_8, 2)
    m = m.astype(bool)
    cls = lab[m]
    counts = {c: round(float((cls == IDX[c]).mean()), 3) for c in SAFE if (cls == IDX[c]).any()}
    surface = max(counts, key=counts.get) if counts else "unknown"
    conflicts = {k: round(float(osm[k][m].mean()), 3) for k in OSM_HAZ_LAYERS if osm[k][m].mean() > 0.02}
    pitch_frac = float(osm["pitch"][m].mean())
    pid = strip_pitch(r, osm["pitch_id"], L, W, meta["extent_m"], meta["gsd_m"])
    pitch = (pitches[pid - 1].get("name") or pitches[pid - 1]["id"]) if pid else None
    lat, lon = offset_latlon(meta["lat"], meta["lon"], r.cx, r.cy)
    return dict(rank=rank, center_latlon=[round(lat, 7), round(lon, 7)], center_local_m=[round(r.cx, 1), round(r.cy, 1)],
                axis_deg=float(r.axis_deg), length_m=round(L, 1), width_m=round(W, 1), open_len_m=round(r.avail_len_m, 1),
                overrun_ok=bool(r.avail_len_m >= need), score=round(float(r.score_mean), 3), surface=surface,
                surface_fracs=counts, slope_max_deg=round(float(slope05[m].max()), 2),
                osm_conflicts=conflicts, on_pitch=bool(pitch_frac >= 0.5), pitch_frac=round(pitch_frac, 2), pitch=pitch,
                corners_px=np.round(poly, 1).tolist())


# ------------------------------------------------------------------ rendering
_LUT = np.zeros((256, 4), np.float32)
for _i, _c in enumerate(CLASSES):
    _r, _g, _b, _a = COLORS[_c]
    _LUT[_i] = (_b, _g, _r, _a / 255.0)
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _text(img, txt, org, scale=0.6, color=(255, 255, 255), thick=1):
    put_text(img, txt, org, scale, color, thick)


def _scale_bar(img, gsd_out: float):
    h, w = img.shape[:2]
    n = int(round(100 / gsd_out))
    x0, y0 = 18, h - 22
    cv2.rectangle(img, (x0 - 6, y0 - 26), (x0 + n + 52, y0 + 10), (0, 0, 0), -1)
    cv2.line(img, (x0, y0), (x0 + n, y0), (255, 255, 255), 3)
    for x in (x0, x0 + n // 2, x0 + n):
        cv2.line(img, (x, y0 - 7), (x, y0 + 4), (255, 255, 255), 2)
    _text(img, "100 m", (x0 + n + 6, y0 + 5), 0.5)
    cx, cy = w - 30, 46                                                      # north arrow
    cv2.arrowedLine(img, (cx, cy + 22), (cx, cy - 18), (255, 255, 255), 3, cv2.LINE_AA, tipLength=0.4)
    _text(img, "N", (cx - 8, cy + 44), 0.65)


GREEN, ORANGE, WHITE, GREY = (60, 220, 60), (0, 165, 255), (255, 255, 255), (190, 190, 190)


def _draw_strip(img, s: dict, scale: float, color, thick: int):
    pts = (np.array(s["corners_px"]) * scale).astype(np.int32)
    cv2.polylines(img, [pts], True, (0, 0, 0), thick + 3, cv2.LINE_AA)
    cv2.polylines(img, [pts], True, color, thick, cv2.LINE_AA)
    a, b = (pts[0] + pts[1]) / 2, (pts[2] + pts[3]) / 2
    cv2.arrowedLine(img, tuple(a.astype(int)), tuple(b.astype(int)), color, 1, cv2.LINE_AA, tipLength=0.12)


def source_line(meta: dict, short: bool = False) -> str:
    im, te = meta["imagery"], meta["terrain"]
    if short:
        return f"Source: {im['name']}, OpenStreetMap"
    return (f"Source: {im['attribution']} ({im['licence']}); terrain: {te['name']}; "
            "map data: OpenStreetMap contributors (ODbL)")


def header(width: int, meta: dict, fused: list, scale: float = 1.0, short_source: bool = False) -> np.ndarray:
    """The one text block every benchmark image carries: location / strips found + full overrun / source."""
    n, n_ok = len(fused), sum(st["overrun_ok"] for st in fused)
    out = np.full((int(round(HEAD_PX * scale)), width, 3), 24, np.uint8)
    x0, th = int(14 * scale), (2 if scale > 0.7 else 1)
    _text(out, f"{meta['name']} ({meta['country']})", (x0, int(38 * scale)), 0.95 * scale, WHITE, th)
    found = f"{n} strip{'s' if n != 1 else ''} found"
    _text(out, found, (x0, int(76 * scale)), 0.75 * scale, WHITE, th)
    dx = cv2.getTextSize(found + "    ", FONT, 0.75 * scale, th)[0][0]
    _text(out, f"{n_ok} with full overrun", (x0 + dx, int(76 * scale)), 0.75 * scale, GREEN, th)
    _text(out, source_line(meta, short_source), (x0, int(106 * scale)), 0.5 * scale if not short_source else 0.6 * scale, GREY, 1)
    return out


def decision_title(decision: dict) -> str:
    """Only says JEV9 when JEV-9B actually made the call."""
    return "JEV9 Decision" if decision.get("decider") == "JEV-9B" else "Planner Decision"


def _title_bar(width: int, title: str, scale: float = 1.0) -> np.ndarray:
    out = np.full((int(round(TITLE_PX * scale)), width, 3), 36, np.uint8)
    _text(out, title, (int(14 * scale), int(30 * scale)), 0.8 * scale, WHITE, 2 if scale > 0.7 else 1)
    return out


def answer_panel(img: np.ndarray, meta: dict, fused: list, decision: dict, panel: int = 960) -> np.ndarray:
    """Imagery + the strips: green = full overrun, orange = short of it; the decided strip is thicker
    (no thick strip when the decision is a manual landing)."""
    s = panel / img.shape[1]
    out = cv2.resize(img, (panel, panel), interpolation=cv2.INTER_AREA)
    chosen = decision.get("choice")
    for st in sorted(fused, key=lambda x: x["rank"] == chosen):          # chosen strip drawn last (on top)
        _draw_strip(out, st, s, GREEN if st["overrun_ok"] else ORANGE, 5 if st["rank"] == chosen else 2)
    _scale_bar(out, meta["gsd_m"] / s)
    return out


def recognition_panel(img: np.ndarray, fused_lab, land_fused, steep, panel: int = 960) -> np.ndarray:
    """What was recognised: land classes, slope above the limit (red hatch) and landable ground (cyan). No strips."""
    base = cv2.resize(img, (panel, panel), interpolation=cv2.INTER_AREA)
    lab = cv2.resize(fused_lab, (panel, panel), interpolation=cv2.INTER_NEAREST)
    col = _LUT[lab]
    a = (col[..., 3] * 0.55)[..., None]
    out = (base.astype(np.float32) * 0.75 * (1 - a) + col[..., :3] * a).astype(np.uint8)
    st_m = cv2.resize(steep.astype(np.uint8), (panel, panel), interpolation=cv2.INTER_NEAREST).astype(bool)
    hatch = (np.add.outer(np.arange(panel), np.arange(panel)) % 14) < 3
    out[st_m & hatch] = (0, 0, 255)
    land = cv2.resize(land_fused.astype(np.uint8), (panel, panel), interpolation=cv2.INTER_NEAREST)
    cnts, _ = cv2.findContours(land, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, cnts, -1, (255, 255, 0), 1, cv2.LINE_AA)
    return out


def render(img: np.ndarray, meta: dict, fused_lab, land_fused, steep, fused: list, decision: dict,
           panel: int = 960) -> np.ndarray:
    gap = 8
    Wt = 2 * panel + gap
    left = np.vstack([_title_bar(panel, decision_title(decision)), answer_panel(img, meta, fused, decision, panel)])
    right = np.vstack([_title_bar(panel, "Recognition Result"), recognition_panel(img, fused_lab, land_fused, steep, panel)])
    body = np.full((left.shape[0], Wt, 3), 24, np.uint8)
    body[:, :panel] = left
    body[:, panel + gap:] = right
    return np.vstack([header(Wt, meta, fused), body])


# ------------------------------------------------------------------ decision (JEV-9B where available)
JEV_STATE = ("Choose where a small fixed-wing UAV (Flite Test Tutor) should attempt an automatic landing, judged from "
             "aerial imagery, maps and terrain only (no wind or live camera data). Each option is a {L:.0f} x {W:.0f} m "
             "strip on ground recognised as landable, with at least {need:.0f} m of open ground along its axis. Prefer "
             "grass, flat ground, long open length and mapped sports pitches. If every strip is marginal, choose the "
             "manual landing.")


def strip_facts(st: dict) -> str:
    """Plain facts about one benchmark strip: only what the benchmark measured, nothing invented."""
    f = (f"{st['surface'].replace('short_', '')} strip, axis {st['axis_deg']:.0f} deg, open length {st['open_len_m']:.0f} m, "
         f"max slope {st['slope_max_deg']:.1f} deg")
    return f + (", on a mapped sports pitch" if st["on_pitch"] else "")


def make_jev(kind: str):
    """JEV-9B scorer, or None -> planner decision. kind: auto (JEV if it loads) | jev (required) | planner."""
    if kind == "planner":
        return None
    from cloudbreak.ground.agent import jev

    try:
        if not jev.installed():
            raise RuntimeError(f"JEV-9B weights not in {jev.default_dir()}")
        scorer = jev.JevScorer()
        scorer.load()
        log("JEV-9B loaded: left panels are JEV9 decisions")
        return scorer
    except Exception as e:  # noqa: BLE001 - missing weights / torch / CUDA
        if kind == "jev":
            raise SystemExit(f"--decider jev: JEV-9B unavailable ({e})")
        log(f"JEV-9B unavailable ({e}); left panels are planner decisions")
        return None


def decide(strips: list, scorer, L: float, W: float, need: float, min_p: float = 0.4) -> dict:
    """Pick a strip. JEV: one 'choice' over the strips with full overrun plus the manual-landing option, accepted
    like jev.decide (beats manual and P >= min_p). Planner: the top-ranked strip with full overrun."""
    feas = [st for st in strips if st["overrun_ok"]][:15]
    if scorer is None:
        return dict(decider="planner", choice=feas[0]["rank"] if feas else None)
    if not feas:
        return dict(decider="JEV-9B", choice=None, p_choice={}, p_manual=None, note="no strip with full overrun")
    from cloudbreak.ground.agent.jev import MANUAL

    probs = scorer.p_choice(JEV_STATE.format(L=L, W=W, need=need), "Which option is the best choice?",
                            [strip_facts(st) for st in feas] + [MANUAL])
    p_manual, scores = probs[-1], {st["rank"]: p for st, p in zip(feas, probs[:-1])}
    best = max(feas, key=lambda st: (scores[st["rank"]], st["score"]))
    ok = scores[best["rank"]] > p_manual and scores[best["rank"]] >= min_p
    return dict(decider="JEV-9B", choice=best["rank"] if ok else None,
                p_choice={str(k): round(v, 3) for k, v in scores.items()}, p_manual=round(p_manual, 3))


# ------------------------------------------------------------------ per site
def solve_site(s: Site, L: float, W: float, cfg: dict, scorer=None) -> dict | None:
    d = site_dir(s)
    if not (d / "meta.json").exists():
        log(f"{s.id}: not fetched, skipping")
        return None
    t0 = time.time()
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    img = cv2.imread(str(d / "imagery.jpg"))
    with gzip.open(d / "osm.json.gz", "rt", encoding="utf-8") as f:
        osm_raw = json.load(f)
    gsd, ext = meta["gsd_m"], meta["extent_m"]
    Lc = cfg["landing"]
    need = L + Lc.get("overrun_margin_m", 0.0)
    dem = load_dem(d, meta)
    slope = slope_deg(dem, meta["terrain"]["res_m"], meta["terrain"]["source"])
    slope05 = cv2.resize(slope, img.shape[1::-1], interpolation=cv2.INTER_LINEAR)
    steep = slope05 > Lc["slope_max_deg"]
    cam, dark, cinfo = camera_labels(img, gsd)
    osm, pitches = osm_layers(osm_raw, meta, img.shape[:2])
    fused = fuse(cam, dark, osm)
    buf = Lc.get("hazard_buffer_m", 1.0)
    out = {}
    for mode, lab in (("camera", cam), ("fused", fused)):
        land = landable_mask(lab, slope05, gsd, buf, Lc["slope_max_deg"])
        raws = search(land, surface_score(lab, slope05, Lc["slope_max_deg"]), gsd, ext, L, W, need,
                      osm["pitch_id"] if mode == "fused" else None)      # camera-only gets no map data at all
        out[mode] = dict(landable_frac=round(float(land.mean()), 4), land=land,
                         strips=[describe(r, i + 1, lab, slope05, osm, pitches, meta, L, W, need) for i, r in enumerate(raws)])
    decision = decide(out["fused"]["strips"], scorer, L, W, need)
    bench = render(img, meta, fused, out["fused"]["land"], steep, out["fused"]["strips"], decision)
    cv2.imwrite(str(d / "benchmark.jpg"), bench, [cv2.IMWRITE_JPEG_QUALITY, 88])
    cv2.imwrite(str(d / "classes.png"), fused)
    hist = lambda lab: {c: round(float((lab == IDX[c]).mean()), 4) for c in CLASSES if (lab == IDX[c]).any()}
    res = dict(
        id=s.id, category=s.category, name=s.name, country=s.country, expect=s.expect, focus=s.focus,
        strip_m=[round(L, 1), round(W, 1)], overrun_need_m=round(need, 1), slope_max_deg=Lc["slope_max_deg"],
        steep_frac=round(float(steep.mean()), 4),
        camera=dict(landable_frac=out["camera"]["landable_frac"], classes=hist(cam), strips=out["camera"]["strips"],
                    strips_on_osm_hazard=sum(bool(x["osm_conflicts"]) for x in out["camera"]["strips"]), **cinfo),
        fused=dict(landable_frac=out["fused"]["landable_frac"], classes=hist(fused), strips=out["fused"]["strips"],
                   strips_on_pitch=sum(x["on_pitch"] for x in out["fused"]["strips"])),
        decision=decision,
        osm_pitches=[dict(id=p["id"], sport=p["sport"]) for p in pitches],
        imagery=meta["imagery"]["attribution"], seconds=round(time.time() - t0, 1),
        label="BENCHMARK (aerial orthophoto + OSM + terrain) - not flight data",
    )
    (d / "result.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    fs, cs = res["fused"], res["camera"]
    log(f"{s.id}: fused {len(fs['strips'])} strips (pitch {fs['strips_on_pitch']}), camera {len(cs['strips'])} "
        f"({cs['strips_on_osm_hazard']} on OSM hazards), landable {fs['landable_frac'] * 100:.1f} %, "
        f"{decision['decider']} picks {decision['choice']}, {res['seconds']} s")
    return res


# ------------------------------------------------------------------ sheets + summary
def _tile(s: Site, r: dict, width: int) -> np.ndarray:
    """Contact-sheet tile: the same header (short source) and title as benchmark.jpg, over the decision panel."""
    meta = json.loads((site_dir(s) / "meta.json").read_text(encoding="utf-8"))
    img = cv2.imread(str(site_dir(s) / "imagery.jpg"))
    sc = width / 960 * 1.1
    dec = r.get("decision", {})
    panel = answer_panel(img, meta, r["fused"]["strips"], dec, panel=width)
    return np.vstack([header(width, meta, r["fused"]["strips"], scale=sc, short_source=True),
                      _title_bar(width, decision_title(dec), scale=sc), panel])


def _grid(tiles: list[np.ndarray], cols: int, gap: int = 6) -> np.ndarray:
    cols = min(cols, len(tiles))
    th, tw = max(t.shape[0] for t in tiles), tiles[0].shape[1]
    rows = (len(tiles) + cols - 1) // cols
    sheet = np.full((rows * th + (rows - 1) * gap, cols * tw + (cols - 1) * gap, 3), 40, np.uint8)
    for i, t in enumerate(tiles):
        rr, cc = divmod(i, cols)
        sheet[rr * (th + gap):rr * (th + gap) + t.shape[0], cc * (tw + gap):cc * (tw + gap) + tw] = t
    return sheet


def sheets_and_summary(results: list[dict]) -> None:
    (ROOT / "_sheets").mkdir(parents=True, exist_ok=True)
    by_id = {r["id"]: r for r in results}
    small = []
    for cat in CATEGORIES:
        done = [(s, by_id[s.id]) for s in SITES if s.category == cat and s.id in by_id]
        if not done:
            continue
        cv2.imwrite(str(ROOT / "_sheets" / f"benchmark_{cat}.jpg"), _grid([_tile(s, r, 600) for s, r in done], 5),
                    [cv2.IMWRITE_JPEG_QUALITY, 85])
        small += [_tile(s, r, 420) for s, r in done]
    if small:
        cv2.imwrite(str(ROOT / "_sheets" / "benchmark_all.jpg"), _grid(small, 5), [cv2.IMWRITE_JPEG_QUALITY, 85])
    (ROOT / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    rows = ["| Site | Category | Country | Strips (full overrun) | Decision | Decided surface | On OSM pitch | "
            "Camera-only strips | Camera strips on OSM hazards | Landable | Image |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in SITES:
        r = by_id.get(s.id)
        if r is None:
            continue
        f, c, dec = r["fused"], r["camera"], r.get("decision", {})
        pick = next((x for x in f["strips"] if x["rank"] == dec.get("choice")), None)
        verdict = f"{dec.get('decider', '?')}: strip {pick['rank']}" if pick else f"{dec.get('decider', '?')}: manual landing"
        rel = f"images/{s.category}/{s.id}/benchmark.jpg"
        rows.append(f"| {s.name} | {s.category} | {s.country} | {len(f['strips'])} ({sum(x['overrun_ok'] for x in f['strips'])}) | "
                    f"{verdict} | {pick['surface'] if pick else '-'} | {f['strips_on_pitch']} | {len(c['strips'])} | "
                    f"{c['strips_on_osm_hazard']} | {f['landable_frac'] * 100:.1f} % | [view]({rel}) |")
    L, W = results[0]["strip_m"] if results else (0, 0)
    (HERE / "RESULTS.md").write_text(
        "# Global benchmark results\n\n"
        f"Generated by `python -m globalbenchmarks.solve` on {time.strftime('%Y-%m-%d %H:%M')}. Strip {L} x {W} m "
        f"(Tutor, `config/aircraft_tutor.toml`); \"full overrun\" = open ground of at least "
        f"{results[0]['overrun_need_m'] if results else '?'} m along the axis. Columns are explained in `README.md`.\n\n"
        "**Benchmark imagery, not flight data.** Qualitative: no hand-labelled ground truth yet; OSM is the reference.\n\n"
        + "\n".join(rows) + "\n\nContact sheets: `images/_sheets/benchmark_<category>.jpg`, `images/_sheets/benchmark_all.jpg`.\n",
        encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated site ids (or substrings)")
    ap.add_argument("--category", help="comma-separated categories")
    ap.add_argument("--strip", type=float, nargs=2, metavar=("L", "W"), help="strip size in m (default: aircraft config)")
    ap.add_argument("--decider", choices=["auto", "jev", "planner"], default="auto",
                    help="who picks the strip on the left panel: JEV-9B if it loads (auto), JEV-9B or fail (jev), planner")
    a = ap.parse_args(argv)
    cfg = load_aircraft()
    L, W = a.strip if a.strip else required_dims(cfg)
    log(f"strip {L:.1f} x {W:.1f} m, overrun {cfg['landing'].get('overrun_margin_m', 0)} m, slope <= "
        f"{cfg['landing']['slope_max_deg']} deg")
    scorer = make_jev(a.decider)
    for s in select(a.only, a.category):
        solve_site(s, L, W, cfg, scorer)
    # summary over every solved site (not just this run's selection)
    results = [json.loads((site_dir(s) / "result.json").read_text(encoding="utf-8")) for s in SITES
               if (site_dir(s) / "result.json").exists()]
    sheets_and_summary(results)
    log(f"summary: {len(results)} sites -> {HERE / 'RESULTS.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
