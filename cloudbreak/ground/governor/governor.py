"""Cloudbreak governor: the ONLY process that writes to the aircraft.

    python -m cloudbreak.ground.governor.governor --target sitl      (or --target real)
    -> approval page http://127.0.0.1:8710/   (served by the governor itself; no LLM text on it)

State machine:
  idle -> prepared   (core asks; governor REBUILDS the mission itself, hashes it, prints a one-time code
                      to THIS console only)
  prepared -> approved  (human types OTP + "LAND <hash4>" on the governor page -> single-use HMAC token)
  approved -> holding   (execute: all checks pass -> signed upload -> read-back hash match -> AUTO @ hold)
  holding -> committed  (commit: last-look + checks pass -> jump past the hold)
  committed -> landed | holding (after a go-around the mission returns to the hold and waits)
  any -> abort          (never needs approval: DO_GO_AROUND on final, else stay in hold / RTL)
Pilot takeover (mode != AUTO) puts the governor in 'pilot' state; it then issues nothing.
"""
from __future__ import annotations

import argparse
import json
import math
import threading
import time
import tomllib
from dataclasses import asdict
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from cloudbreak.common.audit import AuditLog
from cloudbreak.common.clearance import load_terrain, path_clearance
from cloudbreak.common.config import CONFIG_DIR, data_dir, site
from cloudbreak.common.mav import GOVERNOR_SYSID, Link, load_key, mavlink, mission_hash
from cloudbreak.common.missions import LandingSpec, landing_items, path_points, survey_items, takeoff_items, with_jump_back
from cloudbreak.ground.governor.approval import Approvals, Token
from cloudbreak.ground.governor.checks import Context, Snapshot, all_ok, run_checks

PAGE = Path(__file__).parent / "page" / "index.html"


def load_targets() -> dict:
    with open(CONFIG_DIR / "targets.toml", "rb") as f:
        return tomllib.load(f)


def load_gates() -> dict:
    with open(CONFIG_DIR / "flight_gates.toml", "rb") as f:
        return tomllib.load(f)


def build_items(kind: str, spec: dict) -> list:
    """Deterministic mission construction from a spec (the governor never trusts handed-in items)."""
    if kind == "landing":
        return with_jump_back(landing_items(LandingSpec(**spec["landing"])), base_seq=1)
    if kind == "survey":
        s = spec["survey"]
        pre = takeoff_items(s.get("takeoff_alt_m", 40.0)) if s.get("sitl_takeoff") else []
        return pre + survey_items(s["lat"], s["lon"], s["width_m"], s["length_m"], s["heading_deg"], s["alt_m"],
                                  s["spacing_m"], s.get("lead_in_m", 60.0))
    raise ValueError(kind)


class Governor:
    def __init__(self, target_name: str, session: str | None = None):
        self.targets = load_targets()
        if target_name not in self.targets:
            raise SystemExit(f"unknown target {target_name}")
        self.target_name = target_name
        self.t = self.targets[target_name]
        sess = session or time.strftime("%Y%m%d-%H%M%S")
        self.session_dir = Path(data_dir()) / "sessions" / sess
        self.audit = AuditLog(self.session_dir / "audit_governor.jsonl", "governor")
        self.link = Link(self.t["governor_url"], GOVERNOR_SYSID, role="rw", key=load_key(self.t["key"]), name="governor")
        self.approvals = Approvals()
        self.state = "connecting"
        self.prepared: dict | None = None
        self.token: Token | None = None
        self.mission: dict | None = None        # the mission that is on the aircraft (after execute)
        self.site: dict = {}
        self.hold_start: float | None = None
        self.bias_at_approval: float | None = None
        self.last_checks: list = []
        self.fingerprint: dict = {}
        self.param_audit: dict = {}
        self.rtt_ms: float | None = None
        self._ts_sent: dict[int, float] = {}
        self._lock = threading.RLock()
        self.home = (site()["site"]["center_lat"], site()["site"]["center_lon"])
        self.audit.log("governor_start", target=target_name, url=self.t["governor_url"], sysid=self.t["sysid"])
        threading.Thread(target=self._startup, daemon=True).start()
        threading.Thread(target=self._monitor, daemon=True).start()

    # ------------------------------------------------------------------ startup / fingerprint
    def _startup(self):
        try:
            self.link.wait_heartbeat(60)
        except Exception as e:
            self.state = f"no-link: {e}"
            return
        self.refresh_fingerprint()
        with self._lock:
            self.state = "idle"
        self.audit.log("connected", fingerprint=self.fingerprint)

    def refresh_fingerprint(self):
        sim = self.link.get_param("SIM_SPEEDUP", timeout=3)
        t0 = time.perf_counter()
        self.link.command_long(mavlink.MAV_CMD_REQUEST_MESSAGE, mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION, timeout=2)
        self.link.command_long(42428, timeout=2)                  # MAV_CMD_DO_SEND_BANNER (board/firmware strings)
        time.sleep(1.0)
        av = self.link.get("AUTOPILOT_VERSION")
        fw = None
        if av is not None:
            v = av.flight_sw_version
            fw = f"{(v >> 24) & 255}.{(v >> 16) & 255}.{(v >> 8) & 255}"
        board = None
        for tt, m in list(self.link._inbox):
            if tt >= t0 and m.get_type() == "STATUSTEXT":
                txt = m.text
                if any(k in txt for k in ("CoreWing", "SITL", "F405", "Pixhawk", "Matek", "SpeedyBee")):
                    board = txt
        self.fingerprint = dict(sim_param_present=sim is not None, firmware=fw, board=board,
                                sysid=self.link.target_system)
        if self.t["fingerprint"] == "real":
            self.param_audit = self.run_param_audit()

    def run_param_audit(self) -> dict:
        out = {}
        for name, (exp, tol) in self.t.get("param_audit", {}).items():
            v = self.link.get_param(name, timeout=2)
            out[name] = (v, exp, v is not None and abs(v - exp) <= tol)
        return out

    # ------------------------------------------------------------------ telemetry
    def snapshot(self) -> Snapshot:
        L = self.link
        gps, ekf, sysst, gpi = L.get("GPS_RAW_INT"), L.get("EKF_STATUS_REPORT"), L.get("SYS_STATUS"), L.get("GLOBAL_POSITION_INT")
        hb = L.get("HEARTBEAT")
        rc = L.get("RC_CHANNELS")
        return Snapshot(
            sysid=L.target_system, hb_age_s=L.age("HEARTBEAT"), pos_age_s=L.age("GLOBAL_POSITION_INT"),
            att_age_s=min(L.age("ATTITUDE"), L.age("ATTITUDE_QUATERNION")), loss_rate=L.autopilot_loss_rate(),
            rtt_ms=self.rtt_ms, fix_type=getattr(gps, "fix_type", 0), sats=getattr(gps, "satellites_visible", 0),
            hdop=(gps.eph / 100.0) if gps is not None and gps.eph != 65535 else 99.0,
            ekf_flags=getattr(ekf, "flags", None), battery_pct=getattr(sysst, "battery_remaining", None),
            mode=L.flightmode(), armed=bool(hb.base_mode & 128) if hb is not None else False,
            rel_alt_m=(gpi.relative_alt / 1000.0) if gpi is not None else None,
            rc=[getattr(rc, f"chan{i}_raw", 0) for i in range(1, 19)] if rc is not None else [],
            sim_param_present=self.fingerprint.get("sim_param_present"), board=self.fingerprint.get("board"),
            firmware=self.fingerprint.get("firmware"))

    def _monitor(self):
        last_ts = 0.0
        while True:
            time.sleep(0.5)
            now = time.perf_counter()
            try:
                if self.link.target_system is not None and now - last_ts > 2.0:
                    ts1 = time.perf_counter_ns()
                    self._ts_sent[ts1] = now
                    self.link.send("timesync_send", 0, ts1)
                    last_ts = now
                    if len(self._ts_sent) > 10:
                        self._ts_sent.pop(next(iter(self._ts_sent)))
                lt = self.link.latest.get("TIMESYNC")
                if lt is not None and lt.msg.tc1 != 0 and lt.msg.ts1 in self._ts_sent:
                    self.rtt_ms = round((lt.t - self._ts_sent.pop(lt.msg.ts1)) * 1000, 1)   # reply receive time
                self._track_mission()
            except Exception as e:  # never let the monitor die
                self.audit.log("monitor_error", error=repr(e))

    def _track_mission(self):
        with self._lock:
            if not self.mission or self.state not in ("holding", "committed", "pilot"):
                return
            cur = self.link.get("MISSION_CURRENT")
            seq = cur.seq if cur is not None else None
            seqs = self.mission["seq"]
            mode = self.link.flightmode()
            if self.state != "pilot" and mode not in ("AUTO", "?"):
                self.state = "pilot"
                self.audit.log("pilot_takeover", mode=mode, seq=seq)
                return
            if self.state == "pilot":
                if mode == "AUTO" and seq == seqs.get("hold"):
                    self.state = "holding"
                    self.hold_start = time.time()
                    self.audit.log("back_in_hold_after_pilot")
                return
            if self.mission["kind"] != "landing":
                return
            if self.state == "holding" and seq == seqs["hold"] and self.hold_start is None:
                self.hold_start = time.time()
                self.audit.log("hold_reached", seq=seq)
            if self.state == "committed":
                cid = self.mission["candidate_id"]
                st = self.site.get(cid)
                if st is not None and not st.get("valid", False) and seq in (seqs["final1"], seqs["final2"], seqs["touchdown"], seqs["entry"]):
                    self._abort_locked(f"site invalidated: {st.get('reason')}")
                    return
                if seq == seqs["hold"]:
                    self.state = "holding"
                    self.hold_start = time.time()
                    self.audit.log("go_around_complete_back_in_hold")
                gpi = self.link.get("GLOBAL_POSITION_INT")
                if seq == seqs["touchdown"] and gpi is not None and gpi.relative_alt < 1500 and math.hypot(gpi.vx, gpi.vy) < 100:
                    self.state = "landed"
                    self.audit.log("landed", lat=gpi.lat / 1e7, lon=gpi.lon / 1e7)

    # ------------------------------------------------------------------ actions
    def geometry_check(self, kind: str, spec: dict, items: list):
        """Independent re-check of the exact mission: terrain/obstacle clearance (same path model as the
        planner, incl. missed approach) and the working-area fence."""
        from cloudbreak.common.missions import landing_path_points
        from cloudbreak.ground.core.planner.strips import load_aircraft, margins_from_cfg

        cfg = load_aircraft()
        try:
            terrain = load_terrain()
            if kind == "landing":
                ls = LandingSpec(**spec["landing"])
                pts = landing_path_points(ls, cfg["landing"]["missed_climb_gradient"])
                r = path_clearance(pts, self.home[0], self.home[1], ls.touchdown_lat, ls.touchdown_lon, terrain,
                                   margins_from_cfg(cfg))
            else:
                pts = path_points(items, *self.home)
                # surveys: no strip exemption -- use a touchdown point far away
                r = path_clearance(pts, self.home[0], self.home[1], 0.0, 0.0, terrain, margins_from_cfg(cfg))
        except Exception as e:
            return False, f"terrain layers unavailable: {e!r}"
        g = terrain.grid
        from cloudbreak.common.geodesy import lonlat_to_utm

        xmin, ymin, xmax, ymax = g.bounds
        for lat, lon, _ in pts:
            x, y = lonlat_to_utm(lon, lat)
            if not (xmin + 50 < x < xmax - 50 and ymin + 50 < y < ymax - 50):
                return False, f"path leaves the mapped operating area at {lat:.6f},{lon:.6f}"
        return r.ok, r.reason

    def prepare(self, kind: str, spec: dict, candidate_id: str, grid_version: int):
        with self._lock:
            if self.state in ("holding", "committed"):
                raise HTTPException(409, f"cannot prepare while {self.state}")
            items = build_items(kind, spec)
            h = mission_hash(items)
            geo_ok, geo_reason = self.geometry_check(kind, spec, items)
            geo_ok, geo_reason = bool(geo_ok), str(geo_reason)
            p = self.approvals.prepare(h, candidate_id, grid_version, self.target_name, self.t["sysid"], kind)
            self.prepared = dict(kind=kind, spec=spec, items=[i.to_dict() for i in items], hash=h,
                                 candidate_id=candidate_id, grid_version=grid_version, geometry_ok=geo_ok,
                                 geometry_reason=geo_reason, t=time.time())
            self.token = None
            self.state = "prepared"
            self.bias_at_approval = (self.site.get(candidate_id) or {}).get("bias_m")
            word = "LAND" if kind == "landing" else "FLY"
            banner = "=" * 64
            print(f"\n{banner}\n  CLOUDBREAK GOVERNOR [{self.target_name.upper()}] -- approval requested\n"
                  f"  {kind} mission {h[:12]}  candidate {candidate_id}  grid v{grid_version}\n"
                  f"  ONE-TIME CODE:  {p.otp}      confirm text:  {word} {h[:4]}\n"
                  f"  geometry: {geo_reason}\n{banner}\n", flush=True)
            self.audit.log("prepared", kind=kind, mission_hash=h, candidate_id=candidate_id, grid_version=grid_version,
                           spec=spec, geometry_ok=geo_ok, geometry_reason=geo_reason)
            return self.prepared

    def approve(self, mission_hash_: str, otp: str, confirm: str, operator: str):
        with self._lock:
            try:
                tok = self.approvals.mint(mission_hash_, otp, confirm, operator)
            except PermissionError as e:
                self.audit.log("approval_refused", reason=str(e), operator=operator)
                raise HTTPException(403, str(e))
            self.token = tok
            self.state = "approved"
            self.audit.log("approved", operator=operator, mission_hash=tok.mission_hash, exp=tok.exp, nonce=tok.nonce)
            return dict(operator=tok.operator, exp=tok.exp)

    def _context(self, phase: str) -> Context:
        p = self.prepared or {}
        m = self.mission or {}
        kind = p.get("kind") if phase == "upload" else m.get("kind")
        cid = p.get("candidate_id") if phase == "upload" else m.get("candidate_id")
        st = self.site.get(cid) or {}
        tok_ok, tok_reason = self.approvals.verify(self.token) if self.token else (False, "no token")
        rebuilt = mission_hash(build_items(kind, p["spec"])) if phase == "upload" and p else m.get("hash")
        drift = None
        if phase == "commit" and st.get("bias_m") is not None and self.bias_at_approval is not None:
            drift = st["bias_m"] - self.bias_at_approval
        views = st.get("views_since_hold", 0)
        return Context(
            phase=phase, kind=kind or "landing", target_name=self.target_name, target=self.t, snap=self.snapshot(),
            token_ok=tok_ok, token_reason=tok_reason,
            token_hash=self.token.mission_hash if self.token else None,
            token_target=self.token.target if self.token else None, token_sysid=self.token.sysid if self.token else None,
            token_grid_version=self.token.grid_version if self.token else None, rebuilt_hash=rebuilt,
            grid_version_now=st.get("grid_version", p.get("grid_version") if kind != "landing" else None),
            site_valid=bool(st.get("valid")) if kind == "landing" else True, site_reason=st.get("reason", "no site status"),
            last_look_views=int(views or 0), bias_drift_m=drift,
            geometry_ok=p.get("geometry_ok", False) if phase == "upload" else True,
            geometry_reason=p.get("geometry_reason", ""), gates=load_gates() if self.t["fingerprint"] == "real" else {},
            param_audit=self.run_param_audit() if self.t["fingerprint"] == "real" else {})

    def execute(self):
        with self._lock:
            if self.state != "approved" or not self.token or not self.prepared:
                raise HTTPException(409, f"cannot execute in state {self.state}")
            ctx = self._context("upload")
            checks = run_checks(ctx)
            self.last_checks = [c.to_dict() for c in checks]
            tok = self.token
            self.approvals.consume(tok)                  # one attempt per approval
            self.token = None
            if not all_ok(checks):
                self.state = "idle"
                self.audit.log("execute_refused", checks=self.last_checks)
                raise HTTPException(412, "checks failed: " + ", ".join(c.name for c in checks if not c.ok))
            p = self.prepared
            items = build_items(p["kind"], p["spec"])
            try:
                self.link.upload_mission(items)
                back = self.link.download_mission()
            except Exception as e:
                self.state = "idle"
                self.audit.log("upload_failed", error=repr(e))
                raise HTTPException(502, f"upload failed: {e}")
            hb = mission_hash(back)
            if hb != p["hash"]:
                self.state = "idle"
                self.audit.log("readback_mismatch", sent=p["hash"], back=hb)
                raise HTTPException(502, "read-back hash mismatch -- mission NOT activated")
            seq = {it.label: i + 1 for i, it in enumerate(items)}
            self.mission = dict(kind=p["kind"], hash=p["hash"], seq=seq, candidate_id=p["candidate_id"],
                                spec=p["spec"], grid_version=p["grid_version"], t=time.time())
            first = seq.get("hold", 1)
            self.link.set_current(first)
            if self.link.flightmode() != "AUTO" and p["kind"] == "landing":
                self.link.set_mode("AUTO")
            elif p["kind"] == "survey" and self.t["fingerprint"] == "sitl" and self.snapshot().armed:
                self.link.set_mode("AUTO")       # SITL convenience only; on the real aircraft the PILOT selects AUTO
            self.state = "holding" if p["kind"] == "landing" else "surveying"
            self.hold_start = None
            self.audit.log("executed", mission_hash=p["hash"], readback=hb, operator=tok.operator, checks=self.last_checks)
            return dict(state=self.state, mission_hash=p["hash"])

    def commit(self):
        with self._lock:
            if self.state != "holding" or not self.mission:
                raise HTTPException(409, f"cannot commit in state {self.state}")
            checks = run_checks(self._context("commit"))
            self.last_checks = [c.to_dict() for c in checks]
            if not all_ok(checks):
                self.audit.log("commit_refused", checks=self.last_checks)
                raise HTTPException(412, "commit checks failed: " + ", ".join(c.name for c in checks if not c.ok))
            ok = self.link.set_current(self.mission["seq"]["entry"])
            if not ok:
                self.audit.log("commit_failed", reason="DO_SET_MISSION_CURRENT not acknowledged")
                raise HTTPException(502, "commit command not acknowledged")
            self.state = "committed"
            self.audit.log("committed", mission_hash=self.mission["hash"], checks=self.last_checks)
            return dict(state=self.state)

    def look(self):
        """Fly the approved mission's last-look leg over the strip (returns to the hold). No approval needed:
        it is part of the already-approved, clearance-checked mission and stays at hold altitude."""
        with self._lock:
            if self.state != "holding" or not self.mission or "look_a" not in self.mission["seq"]:
                raise HTTPException(409, f"cannot start last look in state {self.state}")
            ok = self.link.set_current(self.mission["seq"]["look_a"])
            self.audit.log("last_look_started", ok=ok)
            return dict(ok=ok)

    def _abort_locked(self, reason: str):
        seqs = (self.mission or {}).get("seq", {})
        cur = self.link.get("MISSION_CURRENT")
        seq = cur.seq if cur is not None else None
        action = "none"
        if self.state == "committed" and seq == seqs.get("touchdown"):
            r = self.link.command_long(mavlink.MAV_CMD_DO_GO_AROUND, 30)
            action = f"DO_GO_AROUND ack={r}"
        elif self.state == "committed" and seqs:
            ok = self.link.set_current(seqs["hold"])
            action = f"back_to_hold ok={ok}"
        elif self.state == "holding":
            action = "remain_in_hold"
        self.state = "holding" if self.mission and self.mission["kind"] == "landing" else self.state
        self.audit.log("abort", reason=reason, seq=seq, action=action)
        return dict(action=action)

    def abort(self, reason: str, rtl: bool = False):
        with self._lock:
            if rtl:
                ok = self.link.set_mode("RTL")
                self.state = "rtl"
                self.audit.log("abort_rtl", reason=reason, ok=ok)
                return dict(action=f"RTL ok={ok}")
            return self._abort_locked(reason)

    def update_site(self, data: dict):
        with self._lock:
            cid = data.get("candidate_id")
            if cid:
                prev = self.site.get(cid, {})
                self.site[cid] = dict(data, t=time.time())
                if prev.get("valid") != data.get("valid"):
                    self.audit.log("site_status", **{k: data.get(k) for k in ("candidate_id", "valid", "reason", "grid_version")})

    def status(self) -> dict:
        s = self.snapshot()
        return dict(state=self.state, target=self.target_name, sysid=self.t["sysid"], fingerprint=self.fingerprint,
                    prepared={k: v for k, v in (self.prepared or {}).items() if k != "spec"} if self.prepared else None,
                    approved=dict(operator=self.token.operator, exp=self.token.exp) if self.token else None,
                    mission={k: v for k, v in (self.mission or {}).items() if k != "spec"} if self.mission else None,
                    checks=self.last_checks, telemetry=asdict(s), site=self.site, hold_start=self.hold_start,
                    mission_current=getattr(self.link.get("MISSION_CURRENT"), "seq", None),
                    audit=self.audit.tail(25), param_audit=self.param_audit)


# ---------------------------------------------------------------------- HTTP API (localhost only)
class PrepareReq(BaseModel):
    kind: str
    spec: dict
    candidate_id: str
    grid_version: int


class ApproveReq(BaseModel):
    mission_hash: str
    otp: str
    confirm: str
    operator: str


class AbortReq(BaseModel):
    reason: str = "operator"
    rtl: bool = False


def make_app(gov: Governor) -> FastAPI:
    app = FastAPI(title="Cloudbreak governor")

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.client and request.client.host not in ("127.0.0.1", "::1", "localhost"):
            return JSONResponse({"error": "governor is localhost-only"}, status_code=403)
        return await call_next(request)

    @app.get("/")
    def page():
        return FileResponse(PAGE)

    @app.get("/api/status")
    def status():
        return JSONResponse(json.loads(json.dumps(gov.status(), default=str)))

    @app.post("/api/prepare")
    def prepare(r: PrepareReq):
        return gov.prepare(r.kind, r.spec, r.candidate_id, r.grid_version)

    @app.post("/api/approve")
    def approve(r: ApproveReq):
        return gov.approve(r.mission_hash, r.otp, r.confirm, r.operator)

    @app.post("/api/execute")
    def execute():
        return gov.execute()

    @app.post("/api/look")
    def look():
        return gov.look()

    @app.post("/api/commit")
    def commit():
        return gov.commit()

    @app.post("/api/abort")
    def abort(r: AbortReq):
        return gov.abort(r.reason, r.rtl)

    @app.post("/api/site")
    def site_status(data: dict):
        gov.update_site(data)
        return {"ok": True}

    return app


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, choices=["sitl", "real"])
    ap.add_argument("--port", type=int, default=8710)
    ap.add_argument("--session", default=None)
    a = ap.parse_args(argv)
    gov = Governor(a.target, a.session)
    print(f"[governor] target={a.target} page http://127.0.0.1:{a.port}/  audit {gov.audit.path}", flush=True)
    uvicorn.run(make_app(gov), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
