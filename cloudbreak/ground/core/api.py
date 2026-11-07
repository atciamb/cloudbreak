"""Core HTTP API + operator UI (127.0.0.1:8700).

/api/ro/*  read-only state for the UI and the agent (the agent's ONLY write is POST /api/ro/proposals)
/api/action/*  operator actions: ask the governor to prepare a mission, inject SYNTHETIC hazards, abort
Approval itself happens only on the governor's own page (http://127.0.0.1:8710).

    python -m cloudbreak.ground.core.api --target sitl --source synthetic --perception oracle
"""
from __future__ import annotations

import argparse
import io
import json
import time
from pathlib import Path

import httpx
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from cloudbreak.common.classes import CLASSES, COLORS
from cloudbreak.common.geodesy import utm_to_lonlat
from cloudbreak.ground.core.service import GOV, Core

UI = Path(__file__).parent / "ui" / "index.html"


def _png(rgba: np.ndarray) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, format="PNG", optimize=False, compress_level=1)
    return buf.getvalue()


def _colormap(v: np.ndarray, lo=0.0, hi=1.0, alpha=170, mask=None):
    t = np.clip((v - lo) / max(hi - lo, 1e-9), 0, 1)
    r = (255 * np.clip(1.5 - np.abs(4 * t - 3), 0, 1)).astype(np.uint8)
    g = (255 * np.clip(1.5 - np.abs(4 * t - 2), 0, 1)).astype(np.uint8)
    b = (255 * np.clip(1.5 - np.abs(4 * t - 1), 0, 1)).astype(np.uint8)
    a = np.full(v.shape, alpha, np.uint8)
    if mask is not None:
        a[~mask] = 0
    return np.dstack([r, g, b, a])


class Proposal(BaseModel):
    candidate_id: str | None
    recommendation: str
    rationale: str
    evidence: list = []
    concerns: list = []
    source: str = "llm"
    grid_version: int | None = None
    model: str | None = None


class Req(BaseModel):
    candidate_id: str | None = None
    idx: int = 0
    kind: str = "person"
    lat: float | None = None
    lon: float | None = None
    sitl_takeoff: bool = False
    alt_m: float = 45.0


def make_app(core: Core) -> FastAPI:
    app = FastAPI(title="Cloudbreak core")
    cache: dict = {}

    @app.get("/")
    def ui():
        return FileResponse(UI)

    @app.get("/api/ro/bounds")
    def bounds():
        g = core.layers.grid
        xmin, ymin, xmax, ymax = g.bounds
        lon0, lat0 = utm_to_lonlat(xmin, ymin)
        lon1, lat1 = utm_to_lonlat(xmax, ymax)
        return dict(sw=[lat0, lon0], ne=[lat1, lon1], home=core.home, target=core.target, source=core.source,
                    perception=core.perception_mode)

    @app.get("/api/ro/state")
    def state():
        p = core.pose()
        with core._lock:
            frames = [dict(id=f.frame_id, t=f.t, footprint=f.footprint, source=f.source, n=f.cells_observed) for f in list(core.frames)[-60:]]
            plan = core.plan
        return JSONResponse(json.loads(json.dumps(dict(
            t=time.time(), pose=p, mode=core.link.flightmode(), track=list(core.track)[-1500:], frames=frames,
            grid=core.ev.summary(), plan=plan, proposal=core.proposal, governor=_gov_brief(core.gov_status),
            wind=core.wind.estimate(), latest_frame=core.latest_frame.__dict__ if core.latest_frame else None,
            scenario=core.renderer.scenario.snapshot() if core.renderer else [], source=core.source,
            perception=core.perception_mode), default=float)))

    @app.get("/api/ro/debug")
    def debug():
        ev = core.ev
        obs = ev.views > 0
        plb = ev.p_safe_lb()[obs]
        return dict(observed=int(obs.sum()), views_hist=np.bincount(np.minimum(ev.views[obs], 15)).tolist(),
                    plb_quantiles={q: round(float(np.quantile(plb, q)), 3) for q in (0.1, 0.25, 0.5, 0.75, 0.9)} if plb.size else {},
                    blocked=int((ev.dyn_block_until > time.time()).sum()), hazard_cells=int(ev.hazard_mask().sum()))

    @app.get("/api/ro/calibrate")
    def calibrate(alpha: float = 0.01, min_views: int = 3):
        """SYNTHETIC-world threshold calibration (conformal-style): truth = the world's class raster.
        tau = smallest threshold such that <= alpha of truly-hazardous observed cells have p_lb >= tau.
        Valid only in simulation; on real imagery redo with labelled frames before flight."""
        from cloudbreak.common.classes import HAZARD_IDX, SAFE_IDX

        ev, L = core.ev, core.layers
        obs = ev.views >= min_views
        plb = ev.p_safe_lb()
        haz = np.isin(L.prior_class, HAZARD_IDX) & obs
        safe = np.isin(L.prior_class, SAFE_IDX) & obs
        if haz.sum() < 50 or safe.sum() < 50:
            return dict(error="not enough observed truth cells", haz=int(haz.sum()), safe=int(safe.sum()))
        h = np.sort(plb[haz])
        k = int(np.ceil((1 - alpha) * (len(h) + 1))) - 1                 # split-conformal quantile
        tau = float(h[min(k, len(h) - 1)]) + 1e-3
        return dict(alpha=alpha, tau_cell=round(tau, 3), n_hazard=int(haz.sum()), n_safe=int(safe.sum()),
                    safe_recall_at_tau=round(float((plb[safe] >= tau).mean()), 3),
                    hazard_pass_rate_at_tau=round(float((plb[haz] >= tau).mean()), 4),
                    safe_plb_quantiles={q: round(float(np.quantile(plb[safe], q)), 3) for q in (0.1, 0.5, 0.9)},
                    hazard_plb_quantiles={q: round(float(np.quantile(plb[haz], q)), 3) for q in (0.5, 0.9, 0.99)})

    @app.get("/api/ro/frame/latest.jpg")
    def frame():
        if not core.latest_jpeg:
            raise HTTPException(404)
        return Response(core.latest_jpeg, media_type="image/jpeg")

    @app.get("/api/ro/layer/{name}.png")
    def layer(name: str):
        key = (name, core.ev.version if name != "ortho" else 0)
        if key in cache:
            return Response(cache[key], media_type="image/png")
        ev, L = core.ev, core.layers
        if name == "ortho":
            img = np.dstack([L.ortho.transpose(1, 2, 0), np.full(L.grid.shape, 255, np.uint8)])
        elif name == "class":
            lut = np.array([COLORS[c] for c in CLASSES], np.uint8)
            img = lut[ev.class_map()]
        elif name == "prior":
            lut = np.array([COLORS[c] for c in CLASSES], np.uint8)
            img = lut[L.prior_class]
        elif name == "psafe":
            img = _colormap(ev.p_safe_lb(), 0, 1, mask=ev.views > 0)
        elif name == "coverage":
            img = _colormap(np.minimum(ev.views, 10).astype(np.float32), 0, 10, mask=ev.views > 0)
        elif name == "hag":
            img = _colormap(np.nan_to_num(L.hag), 0, 25, alpha=140)
        else:
            raise HTTPException(404)
        step = 2 if name != "ortho" else 1
        png = _png(np.ascontiguousarray(img[::step, ::step]))
        for k in [k for k in cache if k[0] == name]:
            cache.pop(k)
        cache[key] = png
        return Response(png, media_type="image/png")

    @app.post("/api/ro/proposals")
    def post_proposal(p: Proposal):
        ids = {c["id"] for c in core.plan.get("candidates", []) if c["feasible"]}
        if p.candidate_id is not None and p.candidate_id not in ids:
            core.audit.log("proposal_rejected", reason="not a feasible candidate", proposal=p.model_dump())
            raise HTTPException(422, "proposal must reference a currently feasible candidate (or null)")
        if p.recommendation not in ("propose", "no_safe_site", "need_coverage"):
            raise HTTPException(422, "bad recommendation")
        core.proposal = p.model_dump()
        core.audit.log("proposal", **core.proposal)
        return {"ok": True}

    @app.post("/api/action/request_approval")
    def request_approval(r: Req):
        try:
            return core.request_approval(r.candidate_id)
        except (ValueError, httpx.HTTPError) as e:
            raise HTTPException(409, str(e))

    @app.post("/api/action/request_survey")
    def request_survey(r: Req):
        try:
            return core.request_survey(r.idx, r.alt_m, r.sitl_takeoff)
        except (IndexError, httpx.HTTPError) as e:
            raise HTTPException(409, str(e))

    @app.post("/api/action/inject")
    def inject(r: Req):
        if core.renderer is None:
            raise HTTPException(409, "hazard injection only exists in the SYNTHETIC world")
        lat, lon = r.lat, r.lon
        if lat is None:
            g = core.gov_status.get("mission") or {}
            c = next((c for c in core.plan.get("candidates", []) if c["id"] == g.get("candidate_id")), None)
            if c is None:
                raise HTTPException(409, "no active landing candidate to drop a hazard on")
            lat, lon = c["touchdown_latlon"]
        core.renderer.scenario.add(r.kind, lat, lon)
        core.audit.log("synthetic_hazard_injected", kind=r.kind, lat=lat, lon=lon)
        return dict(ok=True, lat=lat, lon=lon)

    @app.post("/api/action/clear_scenario")
    def clear():
        if core.renderer:
            core.renderer.scenario.clear()
        return {"ok": True}

    @app.post("/api/action/abort")
    def abort():
        r = httpx.post(f"{GOV}/api/abort", json=dict(reason="operator abort from core UI"), timeout=5)
        return r.json()

    return app


def _gov_brief(g: dict) -> dict:
    if not g:
        return {}
    return {k: g.get(k) for k in ("state", "target", "sysid", "mission", "prepared", "approved", "site", "hold_start",
                                  "mission_current", "checks")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="sitl", choices=["sitl", "real"])
    ap.add_argument("--source", default="synthetic", choices=["synthetic", "pi", "none"])
    ap.add_argument("--perception", default="oracle", choices=["oracle", "aerial", "cabinet"])
    ap.add_argument("--pi-url", default=None)
    ap.add_argument("--port", type=int, default=8700)
    ap.add_argument("--resume", action="store_true", help="load the last saved evidence grid")
    a = ap.parse_args(argv)
    core = Core(a.target, a.source, a.perception, a.pi_url, resume=a.resume)
    core.run()
    print(f"[core] UI http://127.0.0.1:{a.port}/  session {core.session_dir}", flush=True)
    uvicorn.run(make_app(core), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
