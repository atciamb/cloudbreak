"""Onboard capture: camera frames tagged with autopilot pose. Runs on the Pi.

Not implemented yet. Planned flow:
  1. Picamera2 captures frames at a modest resolution and saves them locally
     (record on the Pi first; Wi-Fi is not guaranteed).
  2. A MAVLink reader keeps the latest ATTITUDE and GLOBAL_POSITION_INT.
  3. Each saved frame gets a FrameRecord so the ground side can map it.

Clocks are not shared: the camera sensor timestamp, the Pi's monotonic clock
and the FC's time_boot_ms all differ. Record all three and reconcile them
later (e.g. with MAVLink TIMESYNC) instead of trusting packet arrival time.

Picamera2 is only imported inside the capture loop (once written), so this
module stays importable on the ground laptop.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrameRecord:
    """Metadata written alongside every saved frame."""

    path: str
    pi_monotonic_ns: int  # time.monotonic_ns() when the frame was received
    sensor_timestamp_ns: int | None = None  # from Picamera2 frame metadata
    fc_time_boot_ms: int | None = None  # time_boot_ms of the pose used below
    lat: float | None = None  # degrees
    lon: float | None = None  # degrees
    rel_alt_m: float | None = None  # metres above home
    roll_rad: float | None = None
    pitch_rad: float | None = None
    yaw_rad: float | None = None
