"""Downward camera capture (Raspberry Pi Camera Module 3 / IMX708) with distance-triggered geotag timing.

Every camera frame: quality metrics on the low-res stream (blur = Laplacian variance, clipping).
Selected frames (along-track distance >= trigger_distance_m since the last kept frame, bounded by
min/max interval): full-res JPEG + preview JPEG to the session dir and one JSONL metadata line with
  * SensorTimestamp (ns, CLOCK_BOOTTIME, first-row readout) and ExposureTime
  * t_mid_ns: mid-exposure of the centre row = SensorTimestamp - Exposure/2 + (H/2)*line_time
  * t_mid_fc_ms: same instant on the FC clock (via mavbridge's FcClockModel)
  * the latest pose snapshot (ground recomputes the pose by interpolating the tlog at t_mid_fc)
Blurred/clipped frames are still written but flagged quality_ok=false (the ground decides).

Run: python -m cloudbreak.air.capture --config /etc/cloudbreak/air.toml [--fake]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path

import numpy as np

from cloudbreak.air.config import load_air_config
from cloudbreak.common.timebase import ClockFit, boottime_ns

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def blur_score(y: np.ndarray) -> float:
    small = y[::2, ::2]
    if cv2 is not None:
        return float(cv2.Laplacian(small, cv2.CV_32F).var())
    k = small.astype(np.float32)
    lap = -4 * k[1:-1, 1:-1] + k[:-2, 1:-1] + k[2:, 1:-1] + k[1:-1, :-2] + k[1:-1, 2:]
    return float(lap.var())


def clip_fraction(y: np.ndarray) -> float:
    s = y[::4, ::4]
    return float(np.mean(s >= 250) + np.mean(s <= 5))


def yuv420_planes(arr: np.ndarray, w: int, h: int):
    y = arr[:h, :w]
    u = arr[h:h + h // 4].reshape(h // 2, -1)[:, : w // 2]
    v = arr[h + h // 4: h + h // 2].reshape(h // 2, -1)[:, : w // 2]
    return y, u, v


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Trigger:
    def __init__(self, cam_cfg):
        self.d = cam_cfg["trigger_distance_m"]
        self.tmin = cam_cfg["min_interval_s"]
        self.tmax = cam_cfg["max_interval_s"]
        self.last_t = 0.0
        self.last_ll = None

    def __call__(self, now: float, pose: dict) -> str | None:
        dt = now - self.last_t
        if dt < self.tmin:
            return None
        ll = (pose.get("lat"), pose.get("lon")) if pose.get("lat") is not None else None
        why = None
        if ll and self.last_ll and haversine_m(*self.last_ll, *ll) >= self.d:
            why = "distance"
        elif dt >= self.tmax:
            why = "interval"
        if why:
            self.last_t, self.last_ll = now, ll or self.last_ll
        return why


def read_pose(shm: Path) -> dict:
    try:
        return json.loads(shm.read_text())
    except (OSError, ValueError):
        return {}


class Camera:
    """Picamera2 wrapper; `fake=True` generates frames for laptop-side pipeline testing."""

    def __init__(self, cam_cfg, fake=False):
        self.c = cam_cfg
        self.fake = fake
        self.W, self.H = cam_cfg["width"], cam_cfg["height"]
        self.PW, self.PH = cam_cfg["preview_width"], cam_cfg["preview_height"]
        self.n = 0
        if fake:
            return
        from picamera2 import Picamera2
        from libcamera import controls

        if not Picamera2.global_camera_info():
            # CSI cameras are only found at boot, so a fast restart loop cannot help; on the Zero each restart costs
            # ~10 s of CPU (picamera2 import). Say why once, wait, and let systemd retry about once a minute.
            print("capture: no camera detected (check the ribbon: 22-pin Zero cable, contacts toward the board, "
                  "latches closed; then reboot). Retrying in 60 s.", flush=True)
            time.sleep(60)
            raise SystemExit(3)
        self.picam2 = Picamera2()
        fd = int(1e6 / cam_cfg["fps"])
        config = self.picam2.create_video_configuration(
            main={"size": (self.W, self.H), "format": "YUV420"},
            lores={"size": (self.PW, self.PH), "format": "YUV420"},
            sensor={"output_size": (self.W, self.H)},
            buffer_count=4,
            controls={"FrameDurationLimits": (fd, fd)},
        )
        self.picam2.configure(config)
        ctrl = {"AfMode": controls.AfModeEnum.Manual, "LensPosition": float(cam_cfg["lens_position"])}
        if cam_cfg["exposure_us"] > 0:
            ctrl["ExposureTime"] = int(cam_cfg["exposure_us"])
        else:
            ctrl["AeExposureMode"] = controls.AeExposureModeEnum.Short
        self.picam2.set_controls(ctrl)
        self.picam2.start()
        time.sleep(1.0)
        self.sensor_mode = str(self.picam2.camera_configuration().get("sensor"))

    def grab(self):
        """Returns (main_yuv or None-callable, lores_yuv, metadata, release_fn)."""
        if self.fake:
            time.sleep(1.0 / self.c["fps"])
            self.n += 1
            t = boottime_ns()
            yy, xx = np.mgrid[0:self.PH, 0:self.PW]
            y = ((xx + yy + 7 * self.n) % 256).astype(np.uint8)
            lo = np.vstack([y, np.full((self.PH // 2, self.PW), 128, np.uint8)])
            main = lambda: np.vstack([np.repeat(np.repeat(y, 2, 0), 2, 1),
                                      np.full((self.H // 2, self.W), 128, np.uint8)])
            md = {"SensorTimestamp": t, "ExposureTime": 1000, "AnalogueGain": 1.0, "Lux": 400.0,
                  "LensPosition": 0.0, "FAKE": True}
            return main, lo, md, (lambda: None)
        req = self.picam2.capture_request()
        md = req.get_metadata()
        lo = req.make_array("lores")
        return (lambda: req.make_array("main")), lo, md, req.release


def run(cfg: dict, fake: bool = False):
    import simplejpeg

    cam_cfg = cfg["camera"]
    sdir = Path(cfg["session_dir"])
    (sdir / "frames").mkdir(parents=True, exist_ok=True)
    (sdir / "preview").mkdir(parents=True, exist_ok=True)
    shm = Path(cfg["bridge"]["pose_shm"])
    latest = shm.with_name("cloudbreak_latest.json")
    cam = Camera(cam_cfg, fake=fake)
    trig = Trigger(cam_cfg)
    meta_f = open(sdir / "frames.jsonl", "a", buffering=1)
    nsel = len(list((sdir / "frames").glob("*.jpg")))
    line_ns = cam_cfg["line_time_us"] * 1000.0
    stats = dict(frames=0, selected=nsel, flagged=0, t_start=time.time())
    while True:
        main_fn, lo, md, release = cam.grab()
        try:
            stats["frames"] += 1
            y, u, v = yuv420_planes(lo, cam.PW, cam.PH)
            b = blur_score(y)
            clip = clip_fraction(y)
            pose = read_pose(shm)
            why = trig(time.monotonic(), pose)
            if not why:
                continue
            main = main_fn()
            Y, U, V = yuv420_planes(main, cam.W, cam.H)
            fid = f"f{nsel:06d}"
            nsel += 1
            full = simplejpeg.encode_jpeg_yuv_planes(np.ascontiguousarray(Y), np.ascontiguousarray(U),
                                                     np.ascontiguousarray(V), quality=cam_cfg["jpeg_quality"])
            prev = simplejpeg.encode_jpeg_yuv_planes(np.ascontiguousarray(y), np.ascontiguousarray(u),
                                                     np.ascontiguousarray(v), quality=cam_cfg["preview_quality"])
            (sdir / "frames" / f"{fid}.jpg").write_bytes(full)
            (sdir / "preview" / f"{fid}.jpg").write_bytes(prev)
            ts = int(md.get("SensorTimestamp", boottime_ns()))
            exp_us = float(md.get("ExposureTime", 0))
            t_mid = ts - exp_us * 500.0 + (cam.H / 2) * line_ns
            t_mid_fc_ms = None
            if pose.get("clock"):
                fit = ClockFit(**pose["clock"])
                t_mid_fc_ms = fit.pi_to_fc(t_mid) / 1e6
            ok = b >= cam_cfg["blur_min"] and clip <= cam_cfg["clip_max"]
            stats["flagged"] += 0 if ok else 1
            rec = dict(frame_id=fid, source="fake" if fake else "live", t_sensor_ns=ts, exposure_us=exp_us,
                       t_mid_ns=t_mid, t_mid_fc_ms=t_mid_fc_ms, line_time_us=cam_cfg["line_time_us"],
                       analogue_gain=md.get("AnalogueGain"), digital_gain=md.get("DigitalGain"),
                       colour_gains=md.get("ColourGains"), lux=md.get("Lux"), colour_temp=md.get("ColourTemperature"),
                       lens_position=md.get("LensPosition"), focus_fom=md.get("FocusFoM"),
                       blur=round(b, 1), clip=round(clip, 4), quality_ok=bool(ok), trigger=why,
                       w=cam.W, h=cam.H, pw=cam.PW, ph=cam.PH, camera="imx708_std",
                       pose={k: pose.get(k) for k in ("lat", "lon", "rel_alt", "alt_msl", "vn", "ve", "vd", "hdg", "q",
                                                      "roll", "pitch", "yaw", "groundspeed", "pos_tb_ms", "att_tb_ms",
                                                      "fix", "sats", "armed", "custom_mode")},
                       wall=time.time())
            meta_f.write(json.dumps(rec) + "\n")
            stats["selected"] = nsel
            try:
                tmp = latest.with_suffix(".tmp")
                tmp.write_text(json.dumps(dict(rec, stats=stats)))
                os.replace(tmp, latest)
            except OSError:
                pass
        finally:
            release()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="/etc/cloudbreak/air.toml")
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args(argv)
    run(load_air_config(a.config), fake=a.fake)


if __name__ == "__main__":
    main()
