"""Clock models.

FcClockModel maps flight-controller boot time to companion (Pi) CLOCK_BOOTTIME.

Why one-way: once MAVLink2 signing is enforced on the FC, an unsigned companion's TIMESYNC *requests* are
dropped, so classic two-way NTP-style sync is unavailable without giving the Pi the signing key. Instead we
use the FC's own timestamps (time_boot_ms on every stream message, and the ns-resolution TIMESYNC the FC
broadcasts every ~10 s). For each sample d = t_rx_pi - t_fc = offset + latency, latency >= L_min > 0.
The *lower envelope* of d over time is offset(t) + L_min: we fit a line (offset + drift) to the envelope.
L_min (UART + scheduling, ~1-3 ms at 115200) stays as a small constant bias; two-way TIMESYNC on the bench
(before signing) measures it once (`latency_bias_ns`).
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np

try:
    CLOCK_BOOTTIME = time.CLOCK_BOOTTIME  # Linux
except AttributeError:  # Windows dev
    CLOCK_BOOTTIME = None


def boottime_ns() -> int:
    if CLOCK_BOOTTIME is not None:
        return time.clock_gettime_ns(CLOCK_BOOTTIME)
    return time.perf_counter_ns()


@dataclass
class ClockFit:
    offset_ns: float      # pi_ns - fc_ns at reference pi time t_ref_ns (includes min latency)
    drift_ppm: float
    t_ref_ns: int
    n: int
    resid_ns: float
    latency_bias_ns: float = 0.0

    def fc_to_pi(self, fc_ns: float) -> float:
        # pi = fc + offset + drift*(pi - t_ref)  -> solve approximately (drift tiny)
        approx = fc_ns + self.offset_ns
        return fc_ns + self.offset_ns + self.drift_ppm * 1e-6 * (approx - self.t_ref_ns) - self.latency_bias_ns

    def pi_to_fc(self, pi_ns: float) -> float:
        return pi_ns - self.offset_ns - self.drift_ppm * 1e-6 * (pi_ns - self.t_ref_ns) + self.latency_bias_ns

    def to_dict(self):
        return dict(offset_ns=self.offset_ns, drift_ppm=self.drift_ppm, t_ref_ns=self.t_ref_ns, n=self.n,
                    resid_ns=self.resid_ns, latency_bias_ns=self.latency_bias_ns)


class FcClockModel:
    def __init__(self, window_s: float = 120.0, bin_s: float = 2.0):
        self.window_ns = int(window_s * 1e9)
        self.bin_ns = int(bin_s * 1e9)
        self.samples: deque = deque()          # (t_rx_pi_ns, d_ns, resolution_ns)
        self.latency_bias_ns = 0.0
        self.fit: ClockFit | None = None

    def add(self, t_rx_pi_ns: int, t_fc_ns: int, resolution_ns: int = 1_000_000):
        """resolution_ns: 1e6 for time_boot_ms stamps (add half-ms centring), 1 for TIMESYNC ns."""
        d = t_rx_pi_ns - (t_fc_ns + resolution_ns / 2)
        self.samples.append((t_rx_pi_ns, d))
        while self.samples and t_rx_pi_ns - self.samples[0][0] > self.window_ns:
            self.samples.popleft()

    def add_twoway(self, t_send_pi_ns: int, t_fc_ns: int, t_rx_pi_ns: int):
        """Bench two-way TIMESYNC (pre-signing): measures the one-way min latency bias."""
        rtt = t_rx_pi_ns - t_send_pi_ns
        true_offset = (t_send_pi_ns + rtt / 2) - t_fc_ns
        if self.fit is not None:
            env = self.fit.offset_ns + self.fit.drift_ppm * 1e-6 * (t_rx_pi_ns - self.fit.t_ref_ns)
            self.latency_bias_ns = 0.9 * self.latency_bias_ns + 0.1 * max(0.0, env - true_offset)

    def update(self) -> ClockFit | None:
        if len(self.samples) < 20:
            return self.fit
        a = np.array(self.samples, dtype=np.float64)
        t, d = a[:, 0], a[:, 1]
        # lower envelope: min of d in each time bin
        bins = ((t - t[0]) // self.bin_ns).astype(int)
        uniq = np.unique(bins)
        et, ed = [], []
        for b in uniq:
            m = bins == b
            i = np.argmin(d[m])
            et.append(t[m][i])
            ed.append(d[m][i])
        et, ed = np.array(et), np.array(ed)
        t_ref = int(et[-1])
        if len(et) >= 3:
            A = np.c_[np.ones_like(et), (et - t_ref)]
            coef, *_ = np.linalg.lstsq(A, ed, rcond=None)
            # robust refit: drop envelope points far above the line (bins with no low-latency sample)
            r = ed - A @ coef
            keep = r < np.percentile(r, 75) + 1e5
            coef, *_ = np.linalg.lstsq(A[keep], ed[keep], rcond=None)
            resid = float(np.std(ed[keep] - A[keep] @ coef))
            off, slope = float(coef[0]), float(coef[1])
        else:
            off, slope, resid = float(ed.min()), 0.0, float("nan")
        self.fit = ClockFit(off, slope * 1e6, t_ref, len(self.samples), resid, self.latency_bias_ns)
        return self.fit
