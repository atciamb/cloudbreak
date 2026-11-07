"""Deterministic explanation / proposal (always available; the LLM agent's fallback).

Same output schema as the LLM agent:
  {candidate_id|null, recommendation: propose|no_safe_site|need_coverage, rationale, evidence[], concerns[],
   source: "template", grid_version}
"""
from __future__ import annotations


def explain(plan: dict) -> dict:
    cands = plan.get("candidates", [])
    feas = [c for c in cands if c["feasible"]]
    gv = plan.get("grid_version")
    if feas:
        c = feas[0]
        m = c["metrics"]
        second = feas[1] if len(feas) > 1 else None
        rationale = (f"{c['id']}: {c['length_m']:.0f} x {c['width_m']:.0f} m {c['surface'].replace('_', ' ')} strip, landing heading "
                     f"{c['heading_deg']:.0f} deg, headwind {m['headwind_mps']} m/s, crosswind {m['crosswind_mps']} m/s. "
                     f"Every cell has P(safe) lower bound >= {m['p_lb_min']:.2f} from >= {m['views_min']} camera views; "
                     f"approach and missed approach clear the lidar surface by >= {m['clearance_m']} m. "
                     f"Tightest constraint: {c['binding']}.")
        if second:
            rationale += f" Next best {second['id']} scores {second['score']:.2f} vs {c['score']:.2f}."
        concerns = []
        if m["crosswind_mps"] > 3:
            concerns.append(f"crosswind {m['crosswind_mps']} m/s")
        if (m["clearance_m"] or 0) < 3:
            concerns.append(f"approach clearance only {m['clearance_m']} m")
        if not plan.get("learned_dispersion"):
            concerns.append("strip length uses pre-learning touchdown dispersion")
        return dict(candidate_id=c["id"], recommendation="propose", rationale=rationale,
                    evidence=[dict(layer="evidence_grid", metric="p_lb_min", value=m["p_lb_min"]),
                              dict(layer="lidar_dsm", metric="clearance_m", value=m["clearance_m"]),
                              dict(layer="wind", metric="headwind_mps", value=m["headwind_mps"])],
                    concerns=concerns, source="template", grid_version=gv)
    if cands:
        c = cands[0]
        unknown = next((k for k in c["constraints"] if k["name"] == "unknown_fraction"), None)
        if unknown and unknown["value"] > 0:
            return dict(candidate_id=None, recommendation="need_coverage",
                        rationale=f"Best area {c['id']} still has {unknown['value']:.0%} unobserved cells; survey it before landing. "
                                  f"Binding: {c['binding']}.", evidence=[], concerns=[], source="template", grid_version=gv)
        return dict(candidate_id=None, recommendation="no_safe_site",
                    rationale=f"No strip passes every hard constraint. Closest: {c['id']} fails on {c['binding']}.",
                    evidence=[], concerns=[], source="template", grid_version=gv)
    noms = plan.get("survey_nominations", [])
    return dict(candidate_id=None, recommendation="need_coverage",
                rationale=(f"No observed landable strip yet. Priors nominate {len(noms)} area(s) to survey"
                           + (f"; best at {noms[0]['center_latlon'][0]:.5f},{noms[0]['center_latlon'][1]:.5f} "
                              f"({noms[0]['avail_len_m']:.0f} m open along {noms[0]['axis_deg']:.0f} deg)." if noms else ".")),
                evidence=[], concerns=[], source="template", grid_version=gv)
