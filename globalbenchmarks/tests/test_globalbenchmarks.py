"""Offline tests for the benchmark solver (synthetic images, no network).

    .venv\\Scripts\\python -m pytest globalbenchmarks/tests
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from cloudbreak.common.classes import IDX
from cloudbreak.ground.core.planner.strips import load_aircraft, required_dims
from globalbenchmarks.fetch import bbox_3857, bbox_lonlat, merc, unmerc
from globalbenchmarks.sites import SITES, Site
from globalbenchmarks.solve import (camera_labels, decide, decision_title, fuse, landable_mask, osm_layers, search,
                                    slope_deg, strip_facts, strip_poly_px, surface_score)

GSD, EXT = 0.5, 600.0
N = int(EXT / GSD)
RNG = np.random.default_rng(7)


def _forest(n=N) -> np.ndarray:
    """Tree-canopy-like texture: bright green crowns with dark gaps (~3-6 m)."""
    img = np.zeros((n, n, 3), np.uint8)
    img[:] = (30, 45, 30)                                  # shadowed understory (BGR)
    for _ in range(n * n // 110):
        x, y = (int(v) for v in RNG.integers(0, n, 2))
        r = int(RNG.integers(3, 7))
        g = int(RNG.integers(90, 140))
        cv2.circle(img, (x, y), r, (40, g, 55), -1)
        cv2.circle(img, (x - r // 3, y - r // 3), max(1, r // 2), (60, min(255, g + 40), 80), -1)   # sunlit side
    return img


def _paint_field(img, x0, y0, x1, y1, lines=True):
    img[y0:y1, x0:x1] = (60, 140, 80)                       # mown grass / turf
    noise = RNG.normal(0, 2, (y1 - y0, x1 - x0, 1))
    img[y0:y1, x0:x1] = np.clip(img[y0:y1, x0:x1] + noise, 0, 255).astype(np.uint8)
    if lines:                                               # painted yard lines every ~5 m
        for y in range(y0 + 5, y1, 10):
            img[y, x0:x1] = (235, 240, 235)
    return img


def _meta(lat=40.0, lon=-90.0):
    s = Site("t", "suburban", "t", "US", lat, lon, "naip", "")
    return dict(bbox_3857=list(bbox_3857(s)), gsd_m=GSD, extent_m=EXT, lat=lat, lon=lon)


def _solve(img, dem=None, osm=None):
    cfg = load_aircraft()
    L, W = required_dims(cfg)
    need = L + cfg["landing"]["overrun_margin_m"]
    cam, dark, _ = camera_labels(img, GSD)
    lab = fuse(cam, dark, osm) if osm is not None else cam
    slope = np.zeros(img.shape[:2], np.float32) if dem is None else cv2.resize(dem, img.shape[1::-1])
    land = landable_mask(lab, slope, GSD, cfg["landing"]["hazard_buffer_m"], cfg["landing"]["slope_max_deg"])
    return search(land, surface_score(lab, slope, cfg["landing"]["slope_max_deg"]), GSD, EXT, L, W, need), lab, (L, W, need)


def test_sites_list_shape():
    cats = [s.category for s in SITES]
    assert {c: cats.count(c) for c in set(cats)} == {"urban": 5, "suburban": 5, "rural": 5, "natural": 5, "campus": 2}
    assert len({s.id for s in SITES}) == len(SITES)
    assert all(s.extent_m > EXT for s in SITES if s.category == "campus")
    assert any("affton" in s.id and s.focus for s in SITES)
    assert sum("utah" in s.id for s in SITES) >= 2


def test_mercator_box_is_metric():
    s = Site("t", "rural", "t", "US", 52.5, 5.6, "pdok", "")
    lat, lon = unmerc(*merc(s.lat, s.lon))
    assert abs(lat - s.lat) < 1e-9 and abs(lon - s.lon) < 1e-9
    w, so, e, n = bbox_lonlat(s)
    ns = math.radians(n - so) * 6378137.0
    ew = math.radians(e - w) * 6378137.0 * math.cos(math.radians(s.lat))
    assert abs(ns - EXT) < 2.0 and abs(ew - EXT) < 2.0


def test_turf_with_lines_is_grass_and_canopy_is_tree():
    img = _paint_field(_forest(), 300, 300, 900, 900)
    lab, _, _ = camera_labels(img, GSD)
    field = lab[350:850, 350:850]
    assert (field == IDX["short_grass"]).mean() > 0.85
    assert (lab[:200, :200] == IDX["tree"]).mean() + (lab[:200, :200] == IDX["unknown"]).mean() > 0.9


def test_strip_found_on_field_along_its_long_axis():
    img = _paint_field(_forest(), 520, 300, 680, 900)      # 80 m wide x 300 m long, north-south
    strips, _, (L, W, need) = _solve(img)
    assert strips, "no strip on a 300 m grass field"
    r = strips[0]
    col, row = (r.cx + EXT / 2) / GSD, (EXT / 2 - r.cy) / GSD
    assert 520 < col < 680 and 300 < row < 900
    assert min(r.axis_deg % 180, 180 - r.axis_deg % 180) <= 15     # runs north-south like the field
    assert r.avail_len_m >= need


def test_no_strip_on_short_field_or_steep_field():
    short = _paint_field(_forest(), 500, 500, 700, 580)    # 100 x 40 m: too short across, 16 m strip fits only E-W
    strips, _, (L, W, _) = _solve(short)
    for r in strips:
        assert abs((r.axis_deg % 180) - 90) <= 15            # only east-west fits
    big = _paint_field(_forest(), 200, 200, 1000, 1000)
    yy = np.mgrid[0:600, 0:600][0].astype(np.float32)
    dem = yy * math.tan(math.radians(6.0))                # 6 deg slope everywhere (1 m DEM)
    slope = slope_deg(dem, 1.0, "3dep")
    assert abs(float(np.median(slope)) - 6.0) < 0.2
    strips, _, _ = _solve(big, dem=slope)
    assert strips == []


STRIPS = [   # ranked like solve.search: full overrun first
    dict(rank=1, overrun_ok=True, surface="short_grass", axis_deg=0.0, open_len_m=104.0, slope_max_deg=1.2, on_pitch=False, score=0.9),
    dict(rank=2, overrun_ok=True, surface="short_grass", axis_deg=15.0, open_len_m=172.0, slope_max_deg=0.8, on_pitch=True, score=0.9),
    dict(rank=3, overrun_ok=False, surface="dirt", axis_deg=90.0, open_len_m=60.0, slope_max_deg=2.0, on_pitch=False, score=0.5),
]


class FakeJev:
    def __init__(self, probs):
        self.probs, self.calls = probs, []

    def p_choice(self, state, question, options):
        self.calls.append(options)
        return self.probs


def test_planner_decision_is_top_strip_with_full_overrun():
    d = decide(STRIPS, None, 51, 16, 91)
    assert d == dict(decider="planner", choice=1)
    assert decision_title(d) == "Planner Decision"
    assert decide([STRIPS[2]], None, 51, 16, 91)["choice"] is None       # nothing with full overrun -> manual


def test_jev_decision_sees_only_full_overrun_strips_plus_manual():
    from cloudbreak.ground.agent.jev import MANUAL

    s = FakeJev([0.2, 0.7, 0.1])
    d = decide(STRIPS, s, 51, 16, 91)
    assert d["decider"] == "JEV-9B" and d["choice"] == 2 and decision_title(d) == "JEV9 Decision"
    assert len(s.calls) == 1 and len(s.calls[0]) == 3 and s.calls[0][-1] == MANUAL       # strips 1, 2 + manual; never 3
    assert "mapped sports pitch" in s.calls[0][1] and "None" not in " ".join(s.calls[0][:-1])   # no invented facts
    assert decide(STRIPS, FakeJev([0.2, 0.3, 0.5]), 51, 16, 91)["choice"] is None    # JEV prefers manual -> no strip
    assert strip_facts(STRIPS[0]).startswith("grass strip, axis 0 deg, open length 104 m")


def test_osm_building_on_field_blocks_it_and_pitch_overrides_paint():
    img = _paint_field(_forest(), 400, 300, 800, 900)
    meta = _meta()
    # an OSM building filling the field's centre, and the whole field as a pitch
    x0, y0, x1, y1 = meta["bbox_3857"]

    def ll(col, row):
        mx = x0 + col / N * (x1 - x0)
        my = y1 - row / N * (y1 - y0)
        lat, lon = unmerc(mx, my)
        return dict(lat=lat, lon=lon)

    ring = lambda c0, r0, c1, r1: [ll(c0, r0), ll(c1, r0), ll(c1, r1), ll(c0, r1), ll(c0, r0)]
    osm = dict(elements=[
        dict(type="way", id=1, tags=dict(building="yes"), geometry=ring(400, 550, 800, 650)),
        dict(type="way", id=2, tags=dict(leisure="pitch", sport="soccer"), geometry=ring(400, 300, 800, 900)),
    ])
    layers, pitches = osm_layers(osm, meta, (N, N))
    assert layers["building"][600, 600] and not layers["building"][400, 600]
    assert layers["pitch"][320, 420] and len(pitches) == 1
    strips, lab, (L, W, _) = _solve(img, osm=layers)
    assert lab[600, 600] == IDX["building"]
    assert (lab[320:540, 420:780] == IDX["short_grass"]).mean() > 0.95   # painted lines inside the pitch -> grass
    assert strips, "the field halves either side of the building still hold strips"
    for r in strips:                                        # no strip touches the building
        m = np.zeros((N, N), np.uint8)
        cv2.fillPoly(m, [np.round(strip_poly_px(r, L, W, EXT, GSD)).astype(np.int32)], 1)
        assert not (m.astype(bool) & layers["building"]).any()
