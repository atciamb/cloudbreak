"""Prior layers cropped/resampled onto the working (survey-area) grid."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import rasterio
from rasterio.windows import from_bounds

from cloudbreak.common.config import priors_dir, site
from cloudbreak.common.geodesy import Grid, lonlat_to_utm, site_grid


def working_grid(half_size_m: float = 320.0) -> Grid:
    s = site()["site"]
    x, y = lonlat_to_utm(s["center_lon"], s["center_lat"])
    g = site_grid()
    return g.subgrid(x - half_size_m, y - half_size_m, x + half_size_m, y + half_size_m)


@dataclass
class Layers:
    grid: Grid
    dtm: np.ndarray
    dsm: np.ndarray
    hag: np.ndarray
    slope: np.ndarray
    prior_class: np.ndarray
    prior_conf: np.ndarray
    hazard_dist: np.ndarray
    ortho: np.ndarray          # (3, H, W) uint8
    osm_power: np.ndarray
    osm_barrier: np.ndarray


def _read(name, g: Grid, band=None):
    with rasterio.open(priors_dir("layers") / f"{name}.tif") as src:
        w = from_bounds(*g.bounds, transform=src.transform).round_offsets().round_lengths()
        a = src.read(window=w, boundless=True, fill_value=0)
        return a if band == "all" else a[0]


@lru_cache(maxsize=2)
def load_layers(half_size_m: float = 320.0) -> Layers:
    g = working_grid(half_size_m)
    rd = lambda n, b=None: _read(n, g, b)
    return Layers(g, rd("dtm").astype(np.float32), rd("dsm").astype(np.float32), rd("hag").astype(np.float32),
                  rd("slope").astype(np.float32), rd("prior_class"), rd("prior_conf").astype(np.float32),
                  rd("hazard_dist").astype(np.float32), rd("ortho_rgb", "all"), rd("osm_power"), rd("osm_barrier"))
