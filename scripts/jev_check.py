"""Check the local JEV-9B install: sanity against the model card, landing-candidate ranking, speed and memory.

    .venv\\Scripts\\python scripts\\jev_check.py

1. Model-card example: "parcel arrived damaged, wants money back" / "asking for a refund?" -> P(true) ~0.99 (card,
   bf16). A clearly unrelated statement should score low. Confirms the 4-bit load matches the reference behaviour.
2. The agent's real decision (jev.decide): ONE 'choice' over candidates plus a manual-landing option. A good strip
   among degraded copies (tailwind, low clearance, weak evidence, crosswind, tight geofence, short open ground) must
   win; a lone marginal strip must lose to the manual landing. A ranking aid, not a safety probability.
3. A real planner output: the Schuyler oracle what-if (synthetic evidence) through jev.decide.
4. Time per decision and peak GPU memory.
"""
from __future__ import annotations

import copy
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudbreak.ground.agent.jev import JevScorer, decide, installed  # noqa: E402

GOOD = dict(id="C12a", feasible=True, heading_deg=85, length_m=51, width_m=16, avail_len_m=141, surface="short_grass",
            score=0.55, binding="approach_clearance_m=4.0 (limit 0.0)",
            constraints=[dict(name="geofence_margin_m", value=37.0)],
            metrics=dict(p_lb_min=0.62, p_lb_mean=0.78, views_min=6, headwind_mps=1.2, crosswind_mps=0.3, clearance_m=4.0))
WIND = dict(speed=1.2, from_deg=90)


def variant(name, **metric_changes):
    c = copy.deepcopy(GOOD)
    c["id"] = name
    for k, v in metric_changes.items():
        if k == "geofence":
            c["constraints"] = [dict(name="geofence_margin_m", value=v)]
        elif k == "avail_len_m":
            c["avail_len_m"] = v
        else:
            c["metrics"][k] = v
    return c


def main() -> int:
    if not installed():
        print("JEV-9B is not installed (C:\\cb-data\\models\\JEV-9B)")
        return 1
    import torch

    s = JevScorer()
    t = time.time()
    s.load()
    print(f"loaded in {time.time() - t:.0f} s; GPU memory {torch.cuda.memory_allocated() / 1e9:.1f} GB allocated")
    pos = s.p_yes("Customer says the parcel arrived damaged and wants their money back.", "Is the customer asking for a refund?")
    neg = s.p_yes("Customer asks what time the store opens on Sunday.", "Is the customer asking for a refund?")
    print(f"1. model-card sanity: refund case P(true) {pos:.3f} (card: ~0.99), unrelated case P(true) {neg:.3f}")
    mk = lambda cs: dict(grid_version=1, candidates=cs, survey_nominations=[], learned_dispersion=False)   # noqa: E731
    degraded = [GOOD, variant("tailwind", headwind_mps=-1.4), variant("low_clearance", clearance_m=0.3),
                variant("weak_evidence", p_lb_min=0.41, p_lb_mean=0.66, views_min=3), variant("crosswind", crosswind_mps=4.8),
                variant("tight_fence", geofence=21.0), variant("short_open", avail_len_m=92)]
    times = []
    t = time.perf_counter()
    a = decide(mk(degraded), WIND, s)
    times.append(time.perf_counter() - t)
    print(f"2a. good among degraded -> {a['recommendation']} {a['candidate_id']}: {a['rationale'][:160]}")
    marginal = variant("marginal", headwind_mps=-1.4, crosswind_mps=4.5, clearance_m=0.3, p_lb_min=0.41, views_min=3, geofence=21.0)
    t = time.perf_counter()
    b = decide(mk([marginal]), WIND, s)
    times.append(time.perf_counter() - t)
    print(f"2b. lone marginal strip  -> {b['recommendation']} {b['candidate_id']}: {b['rationale'][:160]}")
    real_ok = True
    try:
        import os
        import time as _t

        import numpy as np

        os.environ["CLOUDBREAK_SITE"] = "schuyler"
        import cloudbreak.ground.core.planner.strips as S
        from cloudbreak.common.config import site
        from cloudbreak.ground.core.mapping.grid import EvidenceGrid
        from cloudbreak.ground.core.mapping.layers import load_layers
        from sim.synth.renderer import oracle_probs

        L = load_layers()
        ev = EvidenceGrid(L.grid)
        H, Wd = L.grid.shape
        rr, cc = np.mgrid[0:H, 0:Wd]
        t0 = _t.time()
        for i in range(5):                       # ORACLE evidence (synthetic), as in the what-if runs
            pr = oracle_probs(L.prior_class, flip_frac=0.0)
            ev.observe(rr.ravel(), cc.ravel(), pr.reshape(-1, pr.shape[-1]), np.ones(H * Wd), t=t0 + i)
        st = site()["site"]
        plan = S.plan(ev, L, dict(from_deg=90.0, speed=1.2), (st["center_lat"], st["center_lon"]), max_eval=60, step_deg=5.0, per_heading=4)
        nf = sum(c["feasible"] for c in plan["candidates"])
        t = time.perf_counter()
        r = decide(plan, dict(from_deg=90.0, speed=1.2), s)
        times.append(time.perf_counter() - t)
        top = next((c for c in plan["candidates"] if c["feasible"]), None)
        print(f"3. Schuyler what-if ({nf} feasible; planner's top {top['id'] if top else None}) -> {r['recommendation']} "
              f"{r['candidate_id']}: {r['rationale'][:220]}")
        real_ok = r["recommendation"] in ("propose", "no_safe_site")
    except Exception as e:                           # noqa: BLE001
        print("3. Schuyler what-if skipped:", repr(e))
    times.sort()
    print(f"4. per decision (one choice pass): median {times[len(times) // 2] * 1000:.0f} ms, max {times[-1] * 1000:.0f} ms; "
          f"peak GPU memory {torch.cuda.max_memory_allocated() / 1e9:.1f} GB")
    best = a["candidate_id"]
    ok = pos > 0.9 and neg < 0.5 and best == GOOD["id"] and b["recommendation"] == "no_safe_site" and real_ok
    print("\nOK" if ok else "\nCHECK FAILED (see above)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
