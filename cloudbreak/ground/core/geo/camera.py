"""Camera model and pixel <-> ground geometry for the downward Camera Module 3 (IMX708, standard lens).

Frames (all right-handed):
  camera  : x right, y down (image rows), z along the optical axis
  body    : FRD (x forward/nose, y right wing, z down)  -- ArduPilot convention
  NED     : x north, y east, z down (ATTITUDE_QUATERNION rotates body -> NED)
  ENU/UTM : x east, y north, z up
Nominal mount: optical axis = body down, image top = nose. `mount_rpy_deg` refines it (boresight).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


def quat_to_R(q):
    """q = (w, x, y, z) body->NED."""
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def euler_to_R(roll, pitch, yaw):
    cr, sr, cp, sp, cy, sy = math.cos(roll), math.sin(roll), math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw)
    return np.array([
        [cp * cy, sr * sp * cy - cr * sy, cr * sp * cy + sr * sy],
        [cp * sy, sr * sp * sy + cr * cy, cr * sp * sy - sr * cy],
        [-sp, sr * cp, cr * cp],
    ])


R_BODY_CAM_NOMINAL = np.array([[0.0, -1.0, 0.0],    # cam x -> body y ; cam y -> body -x ; cam z -> body z
                               [1.0, 0.0, 0.0],
                               [0.0, 0.0, 1.0]])
NED_TO_ENU = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, -1.0]])


@dataclass
class Camera:
    width: int = 2304
    height: int = 1296
    fx: float = 1693.0             # 4.74 mm / 2.8 um (2x2 binned) -- refined by ChArUco
    fy: float = 1693.0
    cx: float = 1152.0
    cy: float = 648.0
    k1: float = 0.0
    k2: float = 0.0
    mount_rpy_deg: tuple = (0.0, 0.0, 0.0)

    def scaled(self, w: int, h: int) -> "Camera":
        sx, sy = w / self.width, h / self.height
        return Camera(w, h, self.fx * sx, self.fy * sy, self.cx * sx, self.cy * sy, self.k1, self.k2, self.mount_rpy_deg)

    @property
    def R_body_cam(self):
        r, p, y = (math.radians(v) for v in self.mount_rpy_deg)
        return euler_to_R(r, p, y) @ R_BODY_CAM_NOMINAL

    @property
    def hfov_deg(self):
        return math.degrees(2 * math.atan(self.width / 2 / self.fx))

    def pixel_rays(self, step: int = 1):
        """Unit rays in the camera frame for a pixel grid (rows, cols) with stride `step` (pixel centres)."""
        v, u = np.mgrid[step / 2:self.height:step, step / 2:self.width:step]
        x = (u - self.cx) / self.fx
        y = (v - self.cy) / self.fy
        if self.k1 or self.k2:   # first-order undistortion
            r2 = x * x + y * y
            f = 1 + self.k1 * r2 + self.k2 * r2 * r2
            x, y = x / f, y / f
        d = np.stack([x, y, np.ones_like(x)], -1)
        return d / np.linalg.norm(d, axis=-1, keepdims=True), u, v

    def project_enu(self, pts_enu: np.ndarray, cam_enu: np.ndarray, R_ned_body: np.ndarray):
        """World ENU points -> pixel (u, v), depth. Points behind the camera get depth <= 0."""
        R_enu_cam = NED_TO_ENU @ R_ned_body @ self.R_body_cam
        pc = (pts_enu - cam_enu) @ R_enu_cam          # rows: world->cam via R^T
        z = pc[..., 2]
        u = self.fx * pc[..., 0] / np.where(z > 1e-6, z, np.nan) + self.cx
        v = self.fy * pc[..., 1] / np.where(z > 1e-6, z, np.nan) + self.cy
        return u, v, z


def ray_ground_intersect(rays_cam: np.ndarray, cam_enu: np.ndarray, R_ned_body: np.ndarray, R_body_cam: np.ndarray,
                         height_fn, iters: int = 6, max_range: float = 400.0):
    """Intersect camera rays with a height field (height_fn(x, y) -> z, e.g. LiDAR DTM or DSM).

    Fixed-point iteration on range t: t_{k+1} = (cam_z - h(p_k)) / (-d_z). Returns ENU points (..., 3) and a
    validity mask (ray points downward and converged within max_range)."""
    R = NED_TO_ENU @ R_ned_body @ R_body_cam
    d = rays_cam @ R.T                               # ENU directions
    dz = d[..., 2]
    down = dz < -0.05
    h0 = height_fn(np.array([cam_enu[0]]), np.array([cam_enu[1]]))[0]
    t = np.where(down, (cam_enu[2] - h0) / np.where(down, -dz, 1.0), np.nan)
    for _ in range(iters):
        p = cam_enu + t[..., None] * d
        h = height_fn(p[..., 0], p[..., 1])
        t_new = (cam_enu[2] - h) / np.where(down, -dz, 1.0)
        t = np.where(np.isfinite(t_new), 0.5 * t + 0.5 * t_new, t)
    p = cam_enu + t[..., None] * d
    ok = down & np.isfinite(t) & (t > 0) & (t < max_range)
    return p, ok, t
