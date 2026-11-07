"""Wind estimation: fuse the autopilot's EKF3 wind, a loiter circle fit, and the forecast/METAR prior.

Inverse-variance fusion of wind vectors (north/east components). Sigmas are deliberately conservative:
  forecast (Open-Meteo 10 m, latest snapshot) sigma 2.5 m/s   | always available offline (cached)
  ArduPlane WIND (EKF3, no airspeed sensor) sigma 1.5 m/s      | only when airborne; best after turns
  loiter circle fit (ground-velocity circle)  sigma from fit   | see wind_circle_fit()
The result carries `from_deg` (meteorological: direction the wind blows FROM), speed, gust and sigma.
"""
from __future__ import annotations

import glob
import json
import math
import time
from pathlib import Path

import numpy as np

from cloudbreak.common.config import priors_dir


def _vec(speed, from_deg):
    # wind blowing FROM from_deg -> velocity vector points to from_deg + 180
    a = math.radians(from_deg + 180.0)
    return np.array([speed * math.cos(a), speed * math.sin(a)])  # (north, east)


def _from(v):
    spd = float(np.hypot(*v))
    to = math.degrees(math.atan2(v[1], v[0]))
    return spd, (to + 180.0) % 360.0


def forecast_wind(now: float | None = None) -> dict | None:
    files = sorted(glob.glob(str(priors_dir("raw") / "weather" / "openmeteo_*.json")))
    if not files:
        return None
    j = json.loads(Path(files[-1]).read_text())
    m = j.get("minutely_15") or j.get("hourly")
    times = m["time"]
    import datetime as dt

    now = now or time.time()
    tz = dt.timezone(dt.timedelta(seconds=j.get("utc_offset_seconds", 0)))
    ts = [dt.datetime.fromisoformat(t).replace(tzinfo=tz).timestamp() for t in times]
    i = int(np.argmin(np.abs(np.array(ts) - now)))
    spd = m["wind_speed_10m"][i]
    d = m["wind_direction_10m"][i]
    gust = m.get("wind_gusts_10m", [None] * len(times))[i]
    return dict(speed=float(spd), from_deg=float(d), gust=float(gust) if gust is not None else None, time=times[i],
                source=Path(files[-1]).name, age_h=round(abs(ts[i] - now) / 3600, 2))


def wind_circle_fit(vn: np.ndarray, ve: np.ndarray):
    """Ground-velocity circle fit (constant-throttle loiter, no airspeed sensor needed).
    Ground velocity g = w + a(theta), |a| = airspeed (approx constant) -> points lie on a circle
    centred at the wind vector w with radius = airspeed. Algebraic (Kasa) fit + residual sigma."""
    x, y = np.asarray(vn, float), np.asarray(ve, float)
    if len(x) < 12:
        return None
    A = np.c_[2 * x, 2 * y, np.ones_like(x)]
    b = x * x + y * y
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cn, ce, c = sol
    r = math.sqrt(max(c + cn * cn + ce * ce, 0.0))
    resid = np.hypot(x - cn, y - ce) - r
    ang = np.unwrap(np.arctan2(y - ce, x - cn))
    coverage = float(min(1.0, (ang.max() - ang.min()) / (2 * math.pi)))
    sigma = float(np.std(resid) / math.sqrt(max(len(x) * coverage, 1.0)) + (1 - coverage) * 2.0)
    spd, frm = _from(np.array([cn, ce]))
    return dict(speed=spd, from_deg=frm, airspeed=r, sigma=sigma, coverage=coverage, n=len(x))


class WindFusion:
    def __init__(self):
        self.fc = None
        self.circle = None
        self.fc_t = 0.0

    def update_fc(self, speed, direction_from, airborne: bool):
        if airborne:
            self.fc = (float(speed), float(direction_from))
            self.fc_t = time.time()

    def update_circle(self, fit: dict | None):
        if fit and fit["coverage"] > 0.7:
            self.circle = fit

    def estimate(self) -> dict:
        parts = []
        fc = forecast_wind()
        if fc:
            parts.append(("forecast", _vec(fc["speed"], fc["from_deg"]), 2.5))
        if self.fc and time.time() - self.fc_t < 30:
            parts.append(("ekf3", _vec(*self.fc), 1.5))
        if self.circle:
            parts.append(("circle_fit", _vec(self.circle["speed"], self.circle["from_deg"]), max(0.3, self.circle["sigma"])))
        if not parts:
            return dict(speed=0.0, from_deg=0.0, gust=None, sigma=5.0, sources=[])
        W = np.array([1 / s ** 2 for _, _, s in parts])
        V = np.array([v for _, v, _ in parts])
        v = (W[:, None] * V).sum(0) / W.sum()
        spd, frm = _from(v)
        return dict(speed=round(spd, 2), from_deg=round(frm, 1), gust=fc.get("gust") if fc else None,
                    sigma=round(float(1 / math.sqrt(W.sum())), 2), sources=[n for n, _, _ in parts],
                    forecast=fc)
