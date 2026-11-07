"""Synthetic downward camera for SITL demos (clearly labelled SYNTHETIC).

For each pixel: ray from the live SITL pose -> intersect the LiDAR DSM (so trees/buildings show parallax)
-> sample the NYS 2024 orthophoto (0.3 m) -> image. Rendered at ~768 px wide (~7 cm/px at 40 m AGL), i.e.
an honest upsample of 30 cm source imagery -- not a fake 2 cm drone image.
Also returns the per-pixel ground-truth class (prior classes + injected dynamic objects) for the ORACLE
segmentation path and for evaluation.

Scenario objects (world-fixed): {"kind": "person"|"vehicle"|"obstacle", "lat":..., "lon":..., "radius_m":...}
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from cloudbreak.common.classes import IDX, K
from cloudbreak.common.geodesy import lonlat_to_utm
from cloudbreak.ground.core.geo.camera import Camera, euler_to_R, quat_to_R, ray_ground_intersect

OBJ_STYLE = {"person": ((235, 60, 200), IDX["person"]), "vehicle": ((240, 140, 20), IDX["vehicle"]),
             "obstacle": ((200, 30, 30), IDX["rough"])}


@dataclass
class Scenario:
    objects: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, kind, lat, lon, radius_m=None):
        r = radius_m or {"person": 0.6, "vehicle": 2.2, "obstacle": 1.0}[kind]
        with self.lock:
            self.objects.append(dict(kind=kind, lat=lat, lon=lon, radius_m=r, t=time.time()))

    def clear(self):
        with self.lock:
            self.objects.clear()

    def snapshot(self):
        with self.lock:
            return list(self.objects)


class Renderer:
    def __init__(self, layers, cam: Camera | None = None, out_w: int = 768, seed: int = 0):
        import rasterio
        from rasterio.windows import from_bounds

        from cloudbreak.common.config import priors_dir

        self.layers = layers
        self.cam = (cam or Camera()).scaled(out_w, int(round(out_w * 1296 / 2304)))
        self.rng = np.random.default_rng(seed)
        g = layers.grid
        with rasterio.open(priors_dir("layers") / "ortho_hr.tif") as src:
            w = from_bounds(*g.bounds, transform=src.transform).round_offsets().round_lengths()
            self.tex = src.read(window=w, boundless=True, fill_value=0).transpose(1, 2, 0).astype(np.float32)
            self.tex_res = src.res[0]
        self.tex_x0, self.tex_y0 = g.x0, g.y0
        dsm = layers.dsm.copy()
        dsm[np.isnan(dsm)] = layers.dtm[np.isnan(dsm)]
        self.dsm = dsm
        self.rays, self.u, self.v = self.cam.pixel_rays(1)
        self.scenario = Scenario()

    def height(self, x, y):
        g = self.layers.grid
        r = np.clip(((g.y0 - y) / g.res).astype(int), 0, g.height - 1)
        c = np.clip(((x - g.x0) / g.res).astype(int), 0, g.width - 1)
        return self.dsm[r, c]

    def _sample_tex(self, x, y):
        fx = (x - self.tex_x0) / self.tex_res - 0.5
        fy = (self.tex_y0 - y) / self.tex_res - 0.5
        H, W = self.tex.shape[:2]
        x0 = np.clip(np.floor(fx).astype(int), 0, W - 2)
        y0 = np.clip(np.floor(fy).astype(int), 0, H - 2)
        ax = np.clip(fx - x0, 0, 1)[..., None]
        ay = np.clip(fy - y0, 0, 1)[..., None]
        t = self.tex
        return (t[y0, x0] * (1 - ax) * (1 - ay) + t[y0, x0 + 1] * ax * (1 - ay) + t[y0 + 1, x0] * (1 - ax) * ay
                + t[y0 + 1, x0 + 1] * ax * ay)

    def render(self, lat, lon, alt_abs, q=None, rpy=None, vel_ne=(0.0, 0.0), exposure_s=0.001):
        """Returns dict(image uint8 HxWx3, truth uint8 HxW, ground_xy HxWx2, valid HxW, cam_enu, R_ned_body)."""
        x, y = lonlat_to_utm(lon, lat)
        cam_enu = np.array([x, y, alt_abs])
        R = quat_to_R(q) if q is not None else euler_to_R(*rpy)
        P, ok, t = ray_ground_intersect(self.rays, cam_enu, R, self.cam.R_body_cam, self.height, iters=7)
        img = self._sample_tex(P[..., 0], P[..., 1])
        g = self.layers.grid
        rr = np.clip(((g.y0 - P[..., 1]) / g.res).astype(int), 0, g.height - 1)
        cc = np.clip(((P[..., 0] - g.x0) / g.res).astype(int), 0, g.width - 1)
        truth = self.layers.prior_class[rr, cc].copy()
        truth[truth == IDX["unknown"]] = IDX["rough"]
        for o in self.scenario.snapshot():
            ox, oy = lonlat_to_utm(o["lon"], o["lat"])
            d = np.hypot(P[..., 0] - ox, P[..., 1] - oy)
            m = (d < o["radius_m"]) & ok
            col, cls = OBJ_STYLE[o["kind"]]
            shade = (0.75 + 0.25 * np.cos(d / o["radius_m"] * math.pi / 2))[..., None]
            img[m] = (np.array(col, np.float32) * shade)[m]
            truth[m] = cls
        # motion blur along the image-projected velocity (exposure * groundspeed / GSD pixels)
        gsd = max(1e-3, (alt_abs - float(self.height(np.array([x]), np.array([y]))[0])) / self.cam.fx)
        blur_px = math.hypot(*vel_ne) * exposure_s / gsd
        if blur_px > 0.8:
            import cv2

            k = int(min(15, round(blur_px)))
            kern = np.zeros((k, k), np.float32)
            kern[k // 2, :] = 1.0 / k
            img = cv2.filter2D(img, -1, kern)
        img = img * self._vignette(img.shape) + self.rng.normal(0, 3.0, img.shape)
        img[~ok] = 20
        img = np.clip(img, 0, 255).astype(np.uint8)
        self._watermark(img)
        truth[~ok] = IDX["unknown"]
        return dict(image=img, truth=truth, ground_xy=P[..., :2], valid=ok, cam_enu=cam_enu, R_ned_body=R, range=t,
                    gsd_m=gsd)

    _vig = None

    def _vignette(self, shape):
        if self._vig is None or self._vig.shape[:2] != shape[:2]:
            h, w = shape[:2]
            yy, xx = np.mgrid[0:h, 0:w]
            r2 = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2
            self._vig = (1 - 0.18 * r2)[..., None].astype(np.float32)
        return self._vig

    @staticmethod
    def _watermark(img):
        import cv2

        cv2.putText(img, "SYNTHETIC", (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(img, "SYNTHETIC", (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 0, 0), 1, cv2.LINE_AA)


def oracle_probs(truth: np.ndarray, p_correct: float = 0.9, flip_frac: float = 0.03, rng=None) -> np.ndarray:
    """ORACLE segmentation: ground-truth labels with calibrated confidence and a few random label flips.
    Clearly labelled SYNTHETIC-ORACLE wherever used."""
    rng = rng or np.random.default_rng()
    lab = truth.copy()
    flip = rng.random(lab.shape) < flip_frac
    lab[flip] = rng.integers(1, K, flip.sum())
    probs = np.full(lab.shape + (K,), (1 - p_correct) / (K - 1), np.float32)
    np.put_along_axis(probs, lab[..., None].astype(np.int64), p_correct, axis=-1)
    return probs
