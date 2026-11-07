"""Geodesy and the shared raster grid.

All map layers (priors, evidence grid, planner rasters) live on one pixel-aligned grid in
EPSG:32618 (WGS84 / UTM 18N). Rows increase southward (north-up GeoTIFF convention).
Mission altitudes are always relative-to-home; absolute heights are only used for terrain
relief (DTM differences), which sidesteps the NAVD88 / EGM96 / ellipsoid mix.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from pyproj import Transformer

UTM_CRS = "EPSG:32618"
WGS84 = "EPSG:4326"


@lru_cache(maxsize=None)
def _tf(src: str, dst: str) -> Transformer:
    return Transformer.from_crs(src, dst, always_xy=True)


def lonlat_to_utm(lon, lat):
    return _tf(WGS84, UTM_CRS).transform(lon, lat)


def utm_to_lonlat(x, y):
    return _tf(UTM_CRS, WGS84).transform(x, y)


@dataclass(frozen=True)
class Grid:
    """North-up grid: x0,y0 = upper-left corner (UTM metres), res = cell size (m)."""

    x0: float
    y0: float
    res: float
    width: int
    height: int
    crs: str = UTM_CRS

    @classmethod
    def from_bbox_lonlat(cls, west, south, east, north, res=0.5, snap=10.0) -> "Grid":
        xs, ys = [], []
        for lon, lat in [(west, south), (west, north), (east, south), (east, north)]:
            x, y = lonlat_to_utm(lon, lat)
            xs.append(x)
            ys.append(y)
        xmin = math.floor(min(xs) / snap) * snap
        xmax = math.ceil(max(xs) / snap) * snap
        ymin = math.floor(min(ys) / snap) * snap
        ymax = math.ceil(max(ys) / snap) * snap
        return cls(xmin, ymax, res, int(round((xmax - xmin) / res)), int(round((ymax - ymin) / res)))

    @property
    def bounds(self):
        """(xmin, ymin, xmax, ymax) in UTM metres."""
        return (self.x0, self.y0 - self.height * self.res, self.x0 + self.width * self.res, self.y0)

    @property
    def shape(self):
        return (self.height, self.width)

    @property
    def transform(self):
        from rasterio.transform import Affine

        return Affine(self.res, 0.0, self.x0, 0.0, -self.res, self.y0)

    def xy_to_rc(self, x, y):
        """UTM -> fractional (row, col) of cell centres' coordinate system (cell (0,0) spans [0,1))."""
        c = (np.asarray(x) - self.x0) / self.res
        r = (self.y0 - np.asarray(y)) / self.res
        return r, c

    def rc_to_xy(self, r, c):
        """Centre of cell (r, c)."""
        x = self.x0 + (np.asarray(c) + 0.5) * self.res
        y = self.y0 - (np.asarray(r) + 0.5) * self.res
        return x, y

    def cell_centers(self):
        xs = self.x0 + (np.arange(self.width) + 0.5) * self.res
        ys = self.y0 - (np.arange(self.height) + 0.5) * self.res
        return xs, ys

    def subgrid(self, xmin, ymin, xmax, ymax) -> "Grid":
        """Pixel-aligned sub-grid covering the given UTM box (clipped to this grid)."""
        c0 = max(0, int(math.floor((xmin - self.x0) / self.res)))
        c1 = min(self.width, int(math.ceil((xmax - self.x0) / self.res)))
        r0 = max(0, int(math.floor((self.y0 - ymax) / self.res)))
        r1 = min(self.height, int(math.ceil((self.y0 - ymin) / self.res)))
        return Grid(self.x0 + c0 * self.res, self.y0 - r0 * self.res, self.res, c1 - c0, r1 - r0, self.crs)

    def to_dict(self):
        return dict(x0=self.x0, y0=self.y0, res=self.res, width=self.width, height=self.height, crs=self.crs)


def site_grid(res: float | None = None) -> Grid:
    from cloudbreak.common.config import site

    s = site()
    b = s["bbox"]
    return Grid.from_bbox_lonlat(b["west"], b["south"], b["east"], b["north"], res or s["grid"]["res_m"])


# ---- local tangent plane helpers (for planner geometry near the field) ----

EARTH_R = 6378137.0


def enu_offset(lat0, lon0, lat, lon):
    """Small-area east/north metres from (lat0, lon0)."""
    dn = math.radians(lat - lat0) * EARTH_R
    de = math.radians(lon - lon0) * EARTH_R * math.cos(math.radians(lat0))
    return de, dn


def offset_latlon(lat0, lon0, de, dn):
    lat = lat0 + math.degrees(dn / EARTH_R)
    lon = lon0 + math.degrees(de / (EARTH_R * math.cos(math.radians(lat0))))
    return lat, lon
