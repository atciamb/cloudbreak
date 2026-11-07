"""System identification from a real ArduPlane DataFlash log (.BIN) -- anchors SITL learning to the Tutor.

    python -m cloudbreak.ground.autoland.sysid path\\to\\flight.BIN

Fits (level / steady segments only, filtered by roll, climb and throttle steadiness):
  * cruise: throttle needed for level flight at each groundspeed band  -> TRIM_THROTTLE suggestion
  * glide: sink rate vs throttle (wings-level descents)                -> TECS_LAND_THR / glide-slope ranges
  * turns: radius vs bank angle  (r = V^2 / (g tan phi))                -> hold/entry loiter radii
Writes C:\\cb-data\\autoland\\sysid.json, which sitl_bo.py and the aircraft config can consume.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from cloudbreak.common.config import data_dir


def load(path: str) -> dict:
    from pymavlink import DFReader

    log = DFReader.DFReader_binary(path)
    cols = {"CTUN": [], "ATT": [], "GPS": [], "BARO": []}
    while True:
        m = log.recv_match(type=list(cols))
        if m is None:
            break
        t = m.get_type()
        d = m.to_dict()
        if t == "CTUN":
            cols[t].append((d["TimeUS"] / 1e6, d.get("ThO", d.get("ThrOut", np.nan)), d.get("NavPitch", np.nan)))
        elif t == "ATT":
            cols[t].append((d["TimeUS"] / 1e6, d["Roll"], d["Pitch"]))
        elif t == "GPS" and d.get("Status", 0) >= 3:
            cols[t].append((d["TimeUS"] / 1e6, d["Spd"], d.get("VZ", np.nan), d["Alt"]))
        elif t == "BARO":
            cols[t].append((d["TimeUS"] / 1e6, d["Alt"], d.get("CRt", np.nan)))
    return {k: np.array(v, float) for k, v in cols.items() if v}


def interp(src, t, col):
    return np.interp(t, src[:, 0], src[:, col])


def fit(path: str) -> dict:
    D = load(path)
    g = D["GPS"]
    t = g[:, 0]
    spd = g[:, 1]
    roll = interp(D["ATT"], t, 1)
    thr = interp(D["CTUN"], t, 1) if "CTUN" in D else np.full_like(t, np.nan)
    crt = interp(D["BARO"], t, 2) if "BARO" in D else -g[:, 2]
    airborne = spd > 6.0
    out = dict(log=Path(path).name, samples=int(airborne.sum()))
    lvl = airborne & (np.abs(roll) < 8) & (np.abs(crt) < 0.5)
    if lvl.sum() > 20:
        out["cruise"] = dict(groundspeed_mps=round(float(np.median(spd[lvl])), 2), throttle_pct=round(float(np.median(thr[lvl])), 1),
                             n=int(lvl.sum()), suggestion=dict(TRIM_THROTTLE=round(float(np.median(thr[lvl])))))
    desc = airborne & (np.abs(roll) < 10) & (crt < -0.3)
    if desc.sum() > 20:
        A = np.c_[np.ones(desc.sum()), thr[desc]]
        coef, *_ = np.linalg.lstsq(A, -crt[desc], rcond=None)
        out["glide"] = dict(sink_at_idle_mps=round(float(coef[0]), 2), sink_per_throttle_pct=round(float(coef[1]), 4),
                            glide_ratio_at_idle=round(float(np.median(spd[desc]) / max(coef[0], 0.1)), 1), n=int(desc.sum()))
        # the steepest glide slope this airframe can hold at throttle T: sink/speed
        T = np.array([0, 10, 20, 30, 40])
        out["glide"]["slope_pct_vs_throttle"] = {int(x): round(float(100 * (coef[0] + coef[1] * x) / max(np.median(spd[desc]), 1)), 1) for x in T}
    turn = airborne & (np.abs(roll) > 15) & (np.abs(roll) < 45)
    if turn.sum() > 20:
        r_pred = spd[turn] ** 2 / (9.81 * np.tan(np.radians(np.abs(roll[turn]))))
        out["turns"] = dict(radius_at_30deg_m=round(float(np.median(spd[turn]) ** 2 / (9.81 * math.tan(math.radians(30)))), 1),
                            median_radius_m=round(float(np.median(r_pred)), 1), n=int(turn.sum()))
    p = data_dir() / "autoland" / "sysid.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(fit(sys.argv[1]), indent=1))
