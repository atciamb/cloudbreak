"""Terrain / obstacle clearance of a mission path against the LiDAR surface model.

Used by the planner (to filter candidates) and independently by the governor (defence in depth: the
governor loads the layers itself and re-checks the exact mission it is about to upload).

Heights: path altitudes are relative to home; absolute = DTM(home) + rel_alt (NAVD88). DSM NaN = no lidar
coverage = unknown obstacle height -> fails unless the path is above UNKNOWN_SAFE_REL_ALT_M.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from cloudbreak.common.geodesy import Grid, enu_offset, lonlat_to_utm

UNKNOWN_SAFE_REL_ALT_M = 60.0


@dataclass
class TerrainLayers:
    grid: Grid
    dtm: np.ndarray
    dsm: np.ndarray            # NaN where no lidar

    def sample(self, lat, lon):
        x, y = lonlat_to_utm(np.asarray(lon), np.asarray(lat))
        r, c = self.grid.xy_to_rc(x, y)
        r = np.clip(np.floor(r).astype(int), 0, self.grid.height - 1)
        c = np.clip(np.floor(c).astype(int), 0, self.grid.width - 1)
        return self.dtm[r, c], self.dsm[r, c]


@lru_cache(maxsize=2)
def load_terrain(res: float = 1.0) -> TerrainLayers:
    """DTM (mean) and DSM (max, conservative) resampled to `res` metres from the 0.5 m prior layers."""
    import rasterio

    from cloudbreak.common.config import priors_dir
    from cloudbreak.common.geodesy import site_grid

    L = priors_dir("layers")
    with rasterio.open(L / "dtm.tif") as s:
        dtm = s.read(1).astype(np.float32)
    with rasterio.open(L / "dsm.tif") as s:
        dsm = s.read(1).astype(np.float32)
    g = site_grid()
    f = max(1, int(round(res / g.res)))
    if f > 1:
        H, W = (g.height // f) * f, (g.width // f) * f
        dtm = dtm[:H, :W].reshape(H // f, f, W // f, f).mean(axis=(1, 3))
        d = dsm[:H, :W].reshape(H // f, f, W // f, f)
        nan_any = np.isnan(d).any(axis=(1, 3))
        dsm = np.where(nan_any, np.nan, np.nanmax(np.where(np.isnan(d), -np.inf, d), axis=(1, 3)))
        g = Grid(g.x0, g.y0, g.res * f, W // f, H // f, g.crs)
    return TerrainLayers(g, dtm, dsm.astype(np.float32))


@dataclass
class ClearanceResult:
    ok: bool
    worst_margin_m: float
    worst_point: tuple | None
    n_points: int
    n_unknown: int
    reason: str


ENROUTE_MARGIN_M = 10.0      # overridable (planner/governor pass the configured values)
FINAL_MARGIN_M = 1.5
STRIP_EXEMPT_M = 40.0
TAPER_M = 250.0


def required_margin(dist_to_td_m: float, enroute=None, final=None, exempt=None, taper=None) -> float:
    """Required clearance above the DSM: `enroute` far out, tapering linearly to `final` at `exempt` metres
    from touchdown; inside `exempt` the strip itself is judged by the evidence grid, not by clearance."""
    enroute = ENROUTE_MARGIN_M if enroute is None else enroute
    final = FINAL_MARGIN_M if final is None else final
    exempt = STRIP_EXEMPT_M if exempt is None else exempt
    taper = TAPER_M if taper is None else taper
    if dist_to_td_m < exempt:
        return -math.inf
    if dist_to_td_m < taper:
        return final + (dist_to_td_m - exempt) * ((enroute - final) / max(taper - exempt, 1.0))
    return enroute


def path_clearance(pts, home_lat, home_lon, td_lat, td_lon, terrain: TerrainLayers, margins: dict | None = None) -> ClearanceResult:
    """pts: [(lat, lon, rel_alt)] from missions.path_points (loiters expanded).
    margins: optional dict(enroute=, final=, exempt=, taper=) overriding the module defaults."""
    margins = margins or {}
    if not pts:
        return ClearanceResult(False, -math.inf, None, 0, 0, "empty path")
    lat = np.array([p[0] for p in pts])
    lon = np.array([p[1] for p in pts])
    rel = np.array([p[2] for p in pts])
    home_dtm, _ = terrain.sample(np.array([home_lat]), np.array([home_lon]))
    dtm, dsm = terrain.sample(lat, lon)
    alt_abs = float(home_dtm[0]) + rel
    worst, wp, nunk = math.inf, None, 0
    for i in range(len(pts)):
        de, dn = enu_offset(td_lat, td_lon, lat[i], lon[i])
        need = required_margin(math.hypot(de, dn), **margins)
        if need == -math.inf:
            continue
        if np.isnan(dsm[i]):
            nunk += 1
            if rel[i] < UNKNOWN_SAFE_REL_ALT_M:
                return ClearanceResult(False, -math.inf, pts[i], len(pts), nunk,
                                       f"unknown obstacle height (no lidar) at {lat[i]:.6f},{lon[i]:.6f} rel_alt {rel[i]:.0f} m")
            continue
        margin = alt_abs[i] - float(dsm[i]) - need
        if margin < worst:
            worst, wp = margin, (float(lat[i]), float(lon[i]), float(rel[i]), float(dsm[i] - home_dtm[0]))
    ok = bool(worst >= 0)
    reason = "ok" if ok else (f"path {-worst:.1f} m below required clearance at {wp[0]:.6f},{wp[1]:.6f} "
                              f"(path {wp[2]:.1f} m, obstacle top {wp[3]:.1f} m rel home)")
    return ClearanceResult(ok, float(worst), wp, len(pts), nunk, reason)
