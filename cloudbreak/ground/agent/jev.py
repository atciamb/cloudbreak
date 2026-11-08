"""JEV yes/no decision model (autotrust/JEV-9B, Apache-2.0, open weights) as the agent's local ranker.

JEV-9B is an open reproduction of TypeSafe AI's Jev "System 1": instead of generating text it reads a state and a
question and returns a calibrated probability in ONE forward pass. Here it only ever answers a yes/no ("noul")
question about each FEASIBLE landing candidate, built from the planner's own numbers, and the agent ranks
candidates by P(yes). It never writes free text, so its output cannot carry instructions; the explanation shown to the
operator stays the deterministic template. The planner's hard constraints, the human approval and the governor are
unchanged.

Its probabilities are calibrated on Jev's training distribution (operational and programmatic decisions), not on
landing sites: treat P(yes) as a ranking score, not a safety probability.

Runs locally, free: weights in C:\\cb-data\\models\\JEV-9B (~18 GB bf16 on disk), loaded in 4-bit NF4 so it fits the
laptop's 8 GB GPU. Needs: transformers, peft, accelerate, bitsandbytes, safetensors (see pyproject [jev] extra).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

QUESTION = ("Should this small fixed-wing UAV attempt an automatic landing on this strip right now, given the "
            "margins, wind, evidence and approach clearance?")

# only the files System 1 needs (the repo also holds reports, videos and a vision variant)
NEEDED = ["config.json", "model.safetensors.index.json", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja",
          "adapter/adapter_config.json", "adapter/adapter_model.safetensors", "head.safetensors", "judge_config.json",
          "calibration.json"] + [f"model-0000{i}-of-00005.safetensors" for i in range(1, 6)]
REPO = "autotrust/JEV-9B"


def default_dir() -> Path:
    from cloudbreak.common.config import data_dir

    return Path(data_dir()) / "models" / "JEV-9B"


def installed(path: Path | None = None) -> bool:
    p = Path(path or default_dir())
    return all((p / f).exists() for f in NEEDED)


def candidate_state(c: dict, wind: dict) -> str:
    """Plain facts about one candidate, from the planner only (no operator or external text)."""
    m = c.get("metrics", {})
    cons = {k["name"]: k for k in c.get("constraints", [])}
    gf = cons.get("geofence_margin_m", {}).get("value")
    return (f"Landing strip {c['length_m']:.0f} m x {c['width_m']:.0f} m, surface {c['surface'].replace('_', ' ')}, "
            f"landing heading {c['heading_deg']:.0f} deg, open length {c['avail_len_m']:.0f} m. "
            f"Wind {wind.get('speed', 0) or 0:.1f} m/s from {wind.get('from_deg', 0) or 0:.0f} deg: headwind "
            f"{m.get('headwind_mps')} m/s, crosswind {m.get('crosswind_mps')} m/s. "
            f"Camera evidence: lowest per-cell P(safe) lower bound {m.get('p_lb_min')}, strip mean {m.get('p_lb_mean')}, "
            f"at least {m.get('views_min')} views per cell. Approach and go-around clear lidar obstacles by "
            f"{m.get('clearance_m')} m" + (f"; the whole pattern stays {gf} m inside the geofence" if gf is not None else "")
            + f". Tightest constraint: {c.get('binding')}. All hard safety constraints are met.")


class JevScorer:
    """Lazy-loaded local JEV-9B System 1 (yes/no only)."""

    def __init__(self, path: Path | None = None, four_bit: bool = True):
        self.path = Path(path or default_dir())
        self.four_bit = four_bit
        self._m = None

    def load(self):
        if self._m is not None:
            return
        import torch
        from peft import PeftModel
        from safetensors.torch import load_file
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        if not torch.cuda.is_available():
            raise RuntimeError("JEV-9B needs a CUDA GPU")
        p = str(self.path)
        tok = AutoTokenizer.from_pretrained(p)
        kw = dict(device_map="cuda", dtype=torch.bfloat16)
        if self.four_bit:
            kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                           bnb_4bit_compute_dtype=torch.bfloat16)
        base = AutoModelForCausalLM.from_pretrained(p, **kw)
        model = PeftModel.from_pretrained(base, p, subfolder="adapter").eval()   # unmerged: safe on 4-bit weights
        # System 1 reads the backbone's last hidden state through its own head; the 248k-token text output layer
        # (~2 GB in bf16) is never used, so free it: the GPU is shared with the camera segmenter.
        model.base_model.model.lm_head = torch.nn.Identity()
        torch.cuda.empty_cache()
        head = load_file(str(self.path / "head.safetensors"))
        cfg = json.loads((self.path / "judge_config.json").read_text())
        temp = json.loads((self.path / "calibration.json").read_text())["per_kind"]
        self._m = dict(torch=torch, tok=tok, model=model, W=head["proj.weight"].cuda().float(),
                       b=head["proj.bias"].cuda().float(), slot=cfg["slots"]["ranges"]["noul"][0], T=temp["noul"])

    def p_choice(self, state: str, question: str, options: list[str]) -> list[float]:
        """JEV 'choice' primitive: one probability per option (2-16), aligned with `options`."""
        if not 2 <= len(options) <= 16:
            raise ValueError("choice needs 2-16 options")
        self.load()
        m = self._m
        torch = m["torch"]
        if "choice_slot" not in m:
            cfg = json.loads((self.path / "judge_config.json").read_text())
            m["choice_slot"] = cfg["slots"]["ranges"]["choice"][0]
            m["T_choice"] = json.loads((self.path / "calibration.json").read_text())["per_kind"]["choice"]
        lines = [f"{'ABCDEFGHIJKLMNOP'[i]}) {o}" for i, o in enumerate(options)]
        text = f"[kind] choice\n[state] {state}\n[question] {question}\n[options]\n" + "\n".join(lines) + "\n[decision]:"
        ids = m["tok"](text, return_tensors="pt", add_special_tokens=False).to("cuda")
        backbone = m["model"].base_model.model.model
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            h = backbone(**ids).last_hidden_state[0, -1].float()
        z = (m["W"] @ h + m["b"]) / m["T_choice"]
        s = m["choice_slot"]
        return torch.softmax(z[s:s + len(options)], 0).tolist()

    def p_yes(self, state: str, question: str = QUESTION) -> float:
        self.load()
        m = self._m
        torch = m["torch"]
        text = f"[kind] noul\n[state] {state}\n[question] {question}\n[options]\nfalse\ntrue\n[decision]:"
        ids = m["tok"](text, return_tensors="pt", add_special_tokens=False).to("cuda")
        backbone = m["model"].base_model.model.model                       # LoRA layers are injected in place
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            h = backbone(**ids).last_hidden_state[0, -1].float()
        z = (m["W"] @ h + m["b"]) / m["T"]
        s = m["slot"]
        p = torch.softmax(z[s:s + 2], 0)
        return float(p[1])


MANUAL = "None of these strips: abandon the autoland, the pilot lands manually"
CHOICE_STATE = ("Choose where a small fixed-wing UAV (Flite Test Tutor) should attempt an automatic landing. Each option is "
                "a grass strip that passed the hard safety limits. Prefer headwind, low crosswind, high obstacle clearance, "
                "strong camera evidence, a wide geofence margin and long open ground. If every strip is marginal, choose "
                "the manual landing. Wind {spd:.1f} m/s from {dir:.0f} deg.")


def candidate_facts(c: dict) -> str:
    m = c.get("metrics", {})
    cons = {k["name"]: k for k in c.get("constraints", [])}
    gf = cons.get("geofence_margin_m", {}).get("value")
    return (f"{c['length_m']:.0f} m strip, landing heading {c['heading_deg']:.0f} deg: headwind {m.get('headwind_mps')} m/s, "
            f"crosswind {m.get('crosswind_mps')} m/s, obstacle clearance {m.get('clearance_m')} m, lowest cell P(safe) "
            f"{m.get('p_lb_min')}, views {m.get('views_min')}"
            + (f", geofence margin {gf} m" if gf is not None else "") + f", open length {c['avail_len_m']:.0f} m")


def decide(plan: dict, wind: dict, scorer, min_p: float = 0.4, max_cands: int = 15) -> dict:
    """ONE JEV 'choice' over the feasible candidates plus an explicit manual-landing option (tested 2026-11-07:
    picks the good strip over degraded copies at 0.90-0.93 in either option order; declines a lone marginal strip).
    Proposes the top candidate only if it beats the manual option and has P >= min_p; otherwise no_safe_site.
    The rationale is the deterministic template plus the probabilities; JEV writes no text."""
    from cloudbreak.ground.agent.template import explain

    feas = [c for c in plan.get("candidates", []) if c["feasible"]][:max_cands]
    if not feas:
        out = explain(plan)                 # need_coverage / no_safe_site, deterministic
        out["source"] = "jev+template"
        return out
    state = CHOICE_STATE.format(spd=float(wind.get("speed") or 0.0), dir=float(wind.get("from_deg") or 0.0))
    probs = scorer.p_choice(state, "Which option is the best choice?", [candidate_facts(c) for c in feas] + [MANUAL])
    p_manual = probs[-1]
    scores = {c["id"]: p for c, p in zip(feas, probs[:-1])}
    best = max(feas, key=lambda c: (scores[c["id"]], c["score"]))
    ranked = ", ".join(f"{cid} {p:.2f}" for cid, p in sorted(scores.items(), key=lambda kv: -kv[1])) + f", manual {p_manual:.2f}"
    evidence = [dict(layer="jev", metric="p_choice", value=round(v, 3), candidate=k) for k, v in scores.items()]
    evidence.append(dict(layer="jev", metric="p_manual", value=round(p_manual, 3)))
    if scores[best["id"]] <= p_manual or scores[best["id"]] < min_p:
        return dict(candidate_id=None, recommendation="no_safe_site",
                    rationale=f"JEV prefers a manual landing over every feasible strip ({ranked}).",
                    evidence=evidence, concerns=["JEV probabilities are a ranking aid, not a safety probability"],
                    source="jev")
    reordered = dict(plan, candidates=[best] + [c for c in plan["candidates"] if c["id"] != best["id"]])
    out = explain(reordered)
    out["rationale"] = (f"JEV picks {best['id']} ({ranked}). " + out["rationale"])[:600]
    out["evidence"] = out.get("evidence", []) + evidence
    out["source"] = "jev"
    return out


def calibrated_softmax_check(z0: float, z1: float, T: float) -> float:
    """P(true) from the two noul logits and the temperature (pure helper, used by tests)."""
    a, b = z0 / T, z1 / T
    mx = max(a, b)
    return math.exp(b - mx) / (math.exp(a - mx) + math.exp(b - mx))
