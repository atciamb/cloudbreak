"""Air-side configuration (TOML at /etc/cloudbreak/air.toml) and per-boot session directory."""
from __future__ import annotations

import os
import time
import tomllib
from pathlib import Path

DEFAULTS = {
    "session_root": "/home/cloudbreak/sessions",
    "bridge": {
        "fc_url": "/dev/serial0",
        "fc_baud": 230400,
        "sysid": 42,
        "ground_hosts": ["192.168.137.1"],
        "ground_udp_port": 14551,
        "uplink_port": 14560,
        "subscribe_port": 14552,
        "pose_shm": "/dev/shm/cloudbreak_pose.json",
    },
    "camera": {
        "width": 2304, "height": 1296,          # IMX708 2x2 binned, full FOV
        "preview_width": 1152, "preview_height": 648,
        "fps": 10.0,
        "exposure_us": 1000,                    # 0 = auto (AeExposureMode Short)
        "lens_position": 0.0,                   # dioptres; 0 = infinity
        "jpeg_quality": 90, "preview_quality": 75,
        "trigger_distance_m": 7.0,              # ~75 % overlap at 40 m AGL
        "min_interval_s": 0.4, "max_interval_s": 2.0,
        "blur_min": 60.0,                       # Laplacian variance on preview Y
        "clip_max": 0.25,                       # max fraction of clipped pixels
        "line_time_us": 13.8,                   # binned-mode row time (refined on the ground)
        "record_h264": False,
    },
    "frameserver": {"port": 8080},
}


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


def current_session_dir(root: str) -> Path:
    """One session per boot: /home/.../sessions/<boot_id[:8]>_<yyyymmdd-hhmm at first use>."""
    rootp = Path(root)
    rootp.mkdir(parents=True, exist_ok=True)
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()[:8]
    except OSError:
        boot = "dev"
    existing = sorted(rootp.glob(f"{boot}_*"))
    if existing:
        return existing[-1]
    d = rootp / f"{boot}_{time.strftime('%Y%m%d-%H%M')}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "frames").mkdir(exist_ok=True)
    (d / "preview").mkdir(exist_ok=True)
    return d


def load_air_config(path: str | os.PathLike | None) -> dict:
    cfg = DEFAULTS
    if path and Path(path).exists():
        with open(path, "rb") as f:
            cfg = _merge(DEFAULTS, tomllib.load(f))
    cfg = dict(cfg)
    cfg["session_dir"] = str(current_session_dir(cfg["session_root"]))
    return cfg
