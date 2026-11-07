"""Pi health probes (no root needed)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

THROTTLE_BITS = {0: "under-voltage now", 1: "arm freq capped now", 2: "throttled now", 3: "soft temp limit now",
                 16: "under-voltage occurred", 17: "freq capped occurred", 18: "throttled occurred",
                 19: "soft temp limit occurred"}


def throttled() -> dict:
    raw = None
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
        raw = int(out.strip().split("=")[1], 16)
    except Exception:
        return dict(raw=None, flags=[])
    return dict(raw=hex(raw), flags=[v for k, v in THROTTLE_BITS.items() if raw & (1 << k)])


def soc_temp_c() -> float | None:
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0
    except OSError:
        return None


def mem_mb() -> dict:
    info = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":")
            info[k] = int(v.split()[0]) // 1024
    except OSError:
        return {}
    return dict(total=info.get("MemTotal"), available=info.get("MemAvailable"))


def snapshot(session_dir: str | None = None) -> dict:
    d = dict(temp_c=soc_temp_c(), throttled=throttled(), mem_mb=mem_mb())
    try:
        d["load"] = os.getloadavg()
    except OSError:
        pass
    if session_dir:
        du = shutil.disk_usage(session_dir)
        d["disk_free_gb"] = round(du.free / 1e9, 2)
    return d
