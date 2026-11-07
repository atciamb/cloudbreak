"""Local LLM landing-site agent (advisory only).

Runs as its own process. It can READ core's state (http://127.0.0.1:8700/api/ro/*) and WRITE exactly one
thing: a schema-validated proposal (POST /api/ro/proposals). It has no route to the governor, no MAVLink,
no code execution, and its output never appears on the governor's approval page.

    python -m cloudbreak.ground.agent.agent [--model qwen3:4b]
"""
from __future__ import annotations

import argparse
import json
import time

import httpx

CORE = "http://127.0.0.1:8700"
OLLAMA = "http://127.0.0.1:11434"

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidate_id", "recommendation", "rationale", "concerns"],
    "properties": {
        "candidate_id": {"type": ["string", "null"]},
        "recommendation": {"type": "string", "enum": ["propose", "no_safe_site", "need_coverage"]},
        "rationale": {"type": "string", "maxLength": 600},
        "concerns": {"type": "array", "items": {"type": "string", "maxLength": 160}, "maxItems": 5},
    },
}

SYSTEM = """You are the advisory landing-site analyst for a small fixed-wing UAV (Flite Test Tutor, no airspeed sensor).
A deterministic planner has already applied every hard safety constraint. Your job: pick the best FEASIBLE candidate
(or say no_safe_site / need_coverage) and explain the choice to the human operator in plain, specific language.
Rules:
- You may only choose a candidate whose "feasible" field is true. Never invent ids.
- You cannot approve, upload or command anything. A human approves on a separate governor page.
- Prefer, in order: clear margins on the binding constraint, headwind (not tailwind), low crosswind, strong evidence
  (high p_lb_min, many views), approach clearance, longer usable length, grass over pavement.
- If no candidate is feasible but some strip is blocked only by unobserved cells, answer need_coverage.
- Mention the single most important risk in concerns. Keep the rationale under 90 words. Output JSON only."""


def compact(plan: dict, wind: dict) -> dict:
    cands = []
    for c in plan.get("candidates", [])[:8]:
        cands.append(dict(id=c["id"], feasible=c["feasible"], heading_deg=c["heading_deg"], length_m=c["length_m"],
                          avail_len_m=c["avail_len_m"], surface=c["surface"], score=c["score"], binding=c["binding"],
                          **{k: c["metrics"].get(k) for k in ("p_lb_min", "p_lb_mean", "views_min", "headwind_mps",
                                                              "crosswind_mps", "clearance_m", "dist_home_m")}))
    return dict(wind=dict(speed_mps=wind.get("speed"), from_deg=wind.get("from_deg"), gust=wind.get("gust"),
                          sources=wind.get("sources")),
                required_strip_m=[plan.get("required_length_m"), plan.get("required_width_m")],
                candidates=cands, survey_nominations=len(plan.get("survey_nominations", [])))


def validate(out: dict, plan: dict) -> tuple[bool, str]:
    feas = {c["id"] for c in plan.get("candidates", []) if c["feasible"]}
    if out.get("recommendation") not in ("propose", "no_safe_site", "need_coverage"):
        return False, "bad recommendation"
    cid = out.get("candidate_id")
    if out["recommendation"] == "propose" and cid not in feas:
        return False, f"proposed {cid!r} is not a feasible candidate"
    if out["recommendation"] != "propose" and cid is not None:
        out["candidate_id"] = None
    if not isinstance(out.get("rationale"), str) or len(out["rationale"]) > 600:
        return False, "bad rationale"
    return True, "ok"


def ask(model: str, payload: dict, timeout: float = 90.0) -> dict:
    r = httpx.post(f"{OLLAMA}/api/chat", json=dict(
        model=model, stream=False, think=False, format=SCHEMA, keep_alive="10m",
        options=dict(temperature=0.2, num_ctx=4096),
        messages=[dict(role="system", content=SYSTEM),
                  dict(role="user", content="Planner output (JSON):\n" + json.dumps(payload, separators=(",", ":")))]),
        timeout=timeout)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def run(model: str, period: float = 8.0):
    last_key = None
    while True:
        try:
            s = httpx.get(f"{CORE}/api/ro/state", timeout=3).json()
            plan = s.get("plan") or {}
            key = (plan.get("grid_version", 0) // 10, tuple((c["id"], c["feasible"]) for c in plan.get("candidates", [])[:5]))
            if plan and key != last_key:
                t0 = time.time()
                out = ask(model, compact(plan, s.get("wind") or {}))
                ok, why = validate(out, plan)
                if ok:
                    body = dict(out, evidence=[], source="llm", model=model, grid_version=plan.get("grid_version"))
                    r = httpx.post(f"{CORE}/api/ro/proposals", json=body, timeout=3)
                    print(f"[agent] {out['recommendation']} {out.get('candidate_id')} ({time.time() - t0:.1f}s) -> core {r.status_code}", flush=True)
                else:
                    print(f"[agent] rejected own output: {why}", flush=True)
                last_key = key
        except Exception as e:
            print(f"[agent] {e!r}", flush=True)
        time.sleep(period)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:4b")
    a = ap.parse_args(argv)
    run(a.model)


if __name__ == "__main__":
    main()
