"""Cloudbreak core: telemetry -> frames -> perception -> DTM projection -> evidence grid -> planner -> governor.

Read-only with respect to the aircraft: core never sends MAVLink. It only *asks* the governor (localhost HTTP)
to prepare a mission, reports site status, and can request an abort (aborts never need approval).

Frame sources: "synthetic" (SITL pose -> renderer, SYNTHETIC), "pi" (pull from the Pi frame server), "none".
Perception: "oracle" (synthetic only, SYNTHETIC-ORACLE), "cabinet" (pretrained aerial segmenter).
"""
from __future__ import annotations

import io
import json
import math
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np

from cloudbreak.common.audit import AuditLog
from cloudbreak.common.classes import CLASSES, DYNAMIC_IDX, IDX, K
from cloudbreak.common.config import REPO_ROOT, data_dir, site
from cloudbreak.common.geodesy import enu_offset, lonlat_to_utm, utm_to_lonlat
from cloudbreak.common.mav import CORE_SYSID, Link
from cloudbreak.ground.core.geo.camera import Camera, euler_to_R, quat_to_R, ray_ground_intersect
from cloudbreak.ground.core.mapping.grid import EvidenceGrid
from cloudbreak.ground.core.mapping.layers import load_layers
from cloudbreak.ground.core.planner.strips import load_aircraft, plan, _strip_cells
from cloudbreak.ground.core.env.weather import WindFusion

sys.path.insert(0, str(REPO_ROOT))   # sim package

GOV = "http://127.0.0.1:8710"


@dataclass
class FrameRecord:
    frame_id: str
    t: float
    source: str
    lat: float
    lon: float
    rel_alt: float
    footprint: list            # [(lat, lon)] 4 corners
    cells_observed: int
    gsd_m: float
    quality: dict = field(default_factory=dict)


class Core:
    def __init__(self, target: str = "sitl", source: str = "synthetic", perception: str = "oracle",
                 pi_url: str | None = None, session: str | None = None, resume: bool = False):
        import tomllib

        from cloudbreak.common.config import CONFIG_DIR

        with open(CONFIG_DIR / "targets.toml", "rb") as f:
            self.targets = tomllib.load(f)
        self.target = target
        self.source, self.perception_mode = source, perception
        self.pi_url = pi_url
        sess = session or time.strftime("%Y%m%d-%H%M%S")
        self.session_dir = Path(data_dir()) / "sessions" / sess
        (self.session_dir / "frames").mkdir(parents=True, exist_ok=True)
        self.audit = AuditLog(self.session_dir / "audit_core.jsonl", "core")
        self.cfg = load_aircraft()
        self.layers = load_layers()
        self.ev = EvidenceGrid(self.layers.grid)
        self.ev.add_prior(self.layers.prior_class, self.layers.prior_conf)
        saved = Path(data_dir()) / "sessions" / "latest_grid.npz"
        if resume and saved.exists():
            self.ev.load(saved)                       # survive a core restart mid-flight
        s = site()["site"]
        self.home = (s["center_lat"], s["center_lon"])
        self.wind = WindFusion()
        self.link = Link(self.targets[target]["core_url"], CORE_SYSID, role="ro", name="core")
        self.frames: deque[FrameRecord] = deque(maxlen=400)
        self.latest_jpeg: bytes | None = None
        self.latest_frame: FrameRecord | None = None
        self.plan: dict = {}
        self.proposal: dict | None = None
        self.gov_status: dict = {}
        self.renderer = None
        self.segmenter = None
        self.track: deque = deque(maxlen=3000)
        self._last_trig = (0.0, None)
        self._lock = threading.RLock()
        self.dtm_home = float(self._dtm(np.array([self.home[1]]), np.array([self.home[0]]))[0])
        self.cam = Camera()
        self.audit.log("core_start", target=target, source=source, perception=perception)
        if source == "synthetic":
            from sim.synth.renderer import Renderer

            self.renderer = Renderer(self.layers)
        if perception in ("aerial", "cabinet"):
            from cloudbreak.ground.core.perception.seg_yolo import AerialSegmenter

            self.segmenter = AerialSegmenter()

    # ------------------------------------------------------------------ helpers
    def _dtm(self, lon, lat):
        g = self.layers.grid
        x, y = lonlat_to_utm(lon, lat)
        r = np.clip(((g.y0 - np.asarray(y)) / g.res).astype(int), 0, g.height - 1)
        c = np.clip(((np.asarray(x) - g.x0) / g.res).astype(int), 0, g.width - 1)
        return self.layers.dtm[r, c]

    def dtm_xy(self, x, y):
        g = self.layers.grid
        r = np.clip(((g.y0 - y) / g.res).astype(int), 0, g.height - 1)
        c = np.clip(((x - g.x0) / g.res).astype(int), 0, g.width - 1)
        return self.layers.dtm[r, c]

    def pose(self):
        gpi, att = self.link.get("GLOBAL_POSITION_INT"), self.link.get("ATTITUDE")
        if gpi is None or att is None:
            return None
        return dict(lat=gpi.lat / 1e7, lon=gpi.lon / 1e7, rel_alt=gpi.relative_alt / 1000.0, vn=gpi.vx / 100.0,
                    ve=gpi.vy / 100.0, roll=att.roll, pitch=att.pitch, yaw=att.yaw, t=time.time())

    # ------------------------------------------------------------------ projection + fusion
    def fuse(self, probs: np.ndarray, cam: Camera, cam_enu, R_ned_body, quality: dict, step: int = 4, veg=None):
        """Project a (H, W, K) probability image onto the evidence grid using the DTM."""
        from cloudbreak.ground.core.geo.camera import NED_TO_ENU

        H, W = probs.shape[:2]
        rays, u, v = cam.pixel_rays(step)
        P, ok, t = ray_ground_intersect(rays, cam_enu, R_ned_body, cam.R_body_cam, self.dtm_xy, iters=6)
        R = NED_TO_ENU @ R_ned_body @ cam.R_body_cam
        d = rays @ R.T
        incidence = np.degrees(np.arccos(np.clip(-d[..., 2], -1, 1)))
        ok &= incidence <= 30.0
        uu = np.clip(u.astype(int), 0, W - 1)
        vv = np.clip(v.astype(int), 0, H - 1)
        p = probs[vv, uu][ok]
        g = self.ev.grid
        r = ((g.y0 - P[..., 1][ok]) / g.res).astype(int)
        c = ((P[..., 0][ok] - g.x0) / g.res).astype(int)
        if veg is not None:      # VDD "vegetation": split by lidar height above ground at the ground point
            vsel = veg[vv, uu][ok]
            if vsel.any():
                hag = self.layers.hag[np.clip(r[vsel], 0, g.height - 1), np.clip(c[vsel], 0, g.width - 1)]
                cls = np.where(np.isnan(hag), IDX["tall_veg"], np.where(hag < 0.3, IDX["short_grass"],
                                                                        np.where(hag < 2.0, IDX["tall_veg"], IDX["tree"])))
                pv = np.full((len(cls), K), 0.15 / (K - 1), np.float32)
                pv[np.arange(len(cls)), cls] = 0.85
                p = p.copy()
                p[vsel] = pv
        gsd = t[ok] / cam.fx
        w = np.cos(np.radians(incidence[ok])) ** 2 * np.clip(0.10 / np.maximum(gsd, 1e-3), 0.2, 1.0)
        w *= float(quality.get("weight", 1.0))
        n = self.ev.observe(r, c, p, w.astype(np.float32))
        corners = []
        for i, j in ((0, 0), (0, -1), (-1, -1), (-1, 0)):        # image corners on the ground
            if np.isfinite(P[i, j]).all():
                lon, lat = utm_to_lonlat(P[i, j, 0], P[i, j, 1])
                corners.append((float(lat), float(lon)))
        return n, corners, float(np.median(gsd)) if gsd.size else 0.0

    # ------------------------------------------------------------------ frame sources
    def _should_trigger(self, pose) -> bool:
        t_last, ll = self._last_trig
        if pose["rel_alt"] < 12:
            return False
        dt = time.time() - t_last
        if dt < 0.4:
            return False
        if ll is not None:
            de, dn = enu_offset(ll[0], ll[1], pose["lat"], pose["lon"])
            if math.hypot(de, dn) < self.cfg["landing"].get("trigger_distance_m", 7.0) and dt < 2.5:
                return False
        self._last_trig = (time.time(), (pose["lat"], pose["lon"]))
        return True

    def synthetic_step(self):
        from sim.synth.renderer import oracle_probs

        pose = self.pose()
        if pose is None or not self._should_trigger(pose):
            return
        if abs(pose["roll"]) > math.radians(35) or abs(pose["pitch"]) > math.radians(20):
            return
        alt_abs = self.dtm_home + pose["rel_alt"]
        out = self.renderer.render(pose["lat"], pose["lon"], alt_abs, rpy=(pose["roll"], pose["pitch"], pose["yaw"]),
                                   vel_ne=(pose["vn"], pose["ve"]))
        cam = self.renderer.cam
        veg = None
        if self.perception_mode == "oracle":
            probs = oracle_probs(out["truth"])
        else:
            probs, veg = self.segmenter.probs_and_veg(out["image"])
        quality = dict(weight=1.0, gsd=out["gsd_m"])
        R = euler_to_R(pose["roll"], pose["pitch"], pose["yaw"])
        x, y = lonlat_to_utm(pose["lon"], pose["lat"])
        n, corners, gsd = self.fuse(probs, cam, np.array([x, y, alt_abs]), R, quality, veg=veg)
        fid = f"s{len(self.frames):06d}"
        self._store_frame(fid, out["image"], pose, corners, n, gsd, "synthetic" + ("-oracle" if self.perception_mode == "oracle" else ""))

    def pi_step(self, client: httpx.Client):
        try:
            meta = client.get(f"{self.pi_url}/latest.json", timeout=1.5).json()
        except Exception:
            return
        fid = meta.get("frame_id")
        if not fid or (self.latest_frame and self.latest_frame.frame_id == fid):
            return
        p = meta.get("pose") or {}
        if p.get("lat") is None or (p.get("rel_alt") or 0) < 5:
            return
        try:
            jpg = client.get(f"{self.pi_url}/frame/{fid}.jpg", params={"w": 1152}, timeout=2.0).content
        except Exception:
            return
        import cv2

        img = cv2.cvtColor(cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        if self.segmenter is None:
            return
        probs, veg = self.segmenter.probs_and_veg(img)
        cam = self.cam.scaled(img.shape[1], img.shape[0])
        R = quat_to_R(p["q"]) if p.get("q") else euler_to_R(p.get("roll", 0), p.get("pitch", 0), p.get("yaw", 0))
        x, y = lonlat_to_utm(p["lon"], p["lat"])
        alt_abs = self.dtm_home + p["rel_alt"]
        q = dict(weight=1.0 if meta.get("quality_ok", True) else 0.3)
        n, corners, gsd = self.fuse(probs, cam, np.array([x, y, alt_abs]), R, q, veg=veg)
        self._store_frame(fid, img, dict(p, t=time.time()), corners, n, gsd, "live")

    def _store_frame(self, fid, img, pose, corners, n, gsd, source):
        from PIL import Image

        buf = io.BytesIO()
        Image.fromarray(img).save(buf, format="JPEG", quality=80)
        with self._lock:
            self.latest_jpeg = buf.getvalue()
            rec = FrameRecord(fid, time.time(), source, pose["lat"], pose["lon"], pose["rel_alt"], corners, n, gsd)
            self.frames.append(rec)
            self.latest_frame = rec
        if len(self.frames) % 5 == 0:
            (self.session_dir / "frames" / f"{fid}.jpg").write_bytes(self.latest_jpeg)
        with open(self.session_dir / "frames.jsonl", "a") as f:
            f.write(json.dumps(rec.__dict__) + "\n")

    # ------------------------------------------------------------------ loops
    def frame_loop(self):
        client = httpx.Client()
        while True:
            try:
                p = self.pose()
                if p is not None:
                    self.track.append((p["lat"], p["lon"], p["rel_alt"]))
                    w = self.link.get("WIND")
                    if w is not None:
                        self.wind.update_fc(w.speed, w.direction, airborne=p["rel_alt"] > 10)
                if self.source == "synthetic":
                    self.synthetic_step()
                elif self.source == "pi":
                    self.pi_step(client)
            except Exception as e:
                self.audit.log("frame_error", error=repr(e))
                time.sleep(1)
            time.sleep(0.1)

    def plan_loop(self):
        last_v = -1
        while True:
            time.sleep(1.0)
            try:
                self.poll_governor()
                if time.time() - getattr(self, "_t_plan", 0) < 8.0:
                    self.report_site()
                    continue
                self._t_plan = time.time()
                if self.ev.version != last_v:
                    last_v = self.ev.version
                    self.cfg = load_aircraft()          # thresholds can be tuned without a restart
                    P = plan(self.ev, self.layers, self.wind.estimate(), self.home, self.cfg)
                    with self._lock:
                        self.plan = P
                    if self.proposal is None or self.proposal.get("grid_version", -1) < P["grid_version"] - 20:
                        from cloudbreak.ground.agent.template import explain

                        self.proposal = explain(P)
                self.report_site()
                if time.time() - getattr(self, "_t_save", 0) > 20:
                    self._t_save = time.time()
                    self.ev.save(Path(data_dir()) / "sessions" / "latest_grid.npz")
            except Exception as e:
                self.audit.log("plan_error", error=repr(e))

    def poll_governor(self):
        try:
            self.gov_status = httpx.get(f"{GOV}/api/status", timeout=1.0).json()
        except Exception:
            self.gov_status = dict(state="unreachable")

    def strip_status(self, spec: dict, since: float | None) -> dict:
        """Is the strip of the governor's mission still landable on the CURRENT grid? + last-look views."""
        L, Wd = self.plan.get("required_length_m", 50), self.plan.get("required_width_m", 15)
        h = math.radians(spec["heading_deg"])
        aim = self.cfg["landing"]["aim_fraction"]
        tdx, tdy = lonlat_to_utm(spec["touchdown_lon"], spec["touchdown_lat"])
        cx, cy = tdx + (0.5 - aim) * L * math.sin(h), tdy + (0.5 - aim) * L * math.cos(h)
        cells = _strip_cells(self.ev.grid, cx, cy, spec["heading_deg"], L, Wd)
        plb = self.ev.p_safe_lb()[cells]
        blocked = (self.ev.dyn_block_until[cells] > time.time()).any()
        haz = self.ev.hazard_mask()[cells].mean()
        Lc = self.cfg["landing"]
        tau_c, tau_s = Lc.get("p_safe_cell_min", Lc["p_safe_min"]), Lc["p_safe_min"]
        valid = bool(plb.min() >= tau_c and plb.mean() >= tau_s and not blocked and haz == 0)
        reason = "ok" if valid else ("dynamic hazard (person/vehicle) on strip" if blocked else
                                     f"hazard cells {haz:.1%}" if haz > 0 else
                                     f"p_safe lower bound min {plb.min():.2f} < {tau_c}" if plb.min() < tau_c else
                                     f"strip mean p_safe lower bound {plb.mean():.2f} < {tau_s}")
        views = 0
        if since:
            clon, clat = utm_to_lonlat(cx, cy)
            for fr in list(self.frames):
                if fr.t >= since and fr.footprint and _inside((clat, clon), fr.footprint):
                    views += 1
        return dict(valid=valid, reason=reason, views_since_hold=views, grid_version=self.ev.version)

    def report_site(self):
        g = self.gov_status
        m = g.get("mission") or g.get("prepared")
        if not m or not m.get("candidate_id"):
            return
        spec = None
        for c in self.plan.get("candidates", []):
            if c["id"] == m["candidate_id"]:
                spec = c["spec"]
        spec = spec or (self._mission_specs.get(m["candidate_id"]) if hasattr(self, "_mission_specs") else None)
        if spec is None:
            return
        st = self.strip_status(spec, g.get("hold_start"))
        try:
            httpx.post(f"{GOV}/api/site", json=dict(candidate_id=m["candidate_id"], **st), timeout=1.0)
        except Exception:
            pass

    # ------------------------------------------------------------------ actions
    def request_approval(self, candidate_id: str):
        c = next((c for c in self.plan.get("candidates", []) if c["id"] == candidate_id), None)
        if c is None:
            raise ValueError("unknown candidate")
        if not c["feasible"]:
            raise ValueError(f"candidate {candidate_id} is not feasible: {c['binding']}")
        if not hasattr(self, "_mission_specs"):
            self._mission_specs = {}
        self._mission_specs[candidate_id] = c["spec"]
        st = self.strip_status(c["spec"], None)
        httpx.post(f"{GOV}/api/site", json=dict(candidate_id=candidate_id, **st), timeout=2.0)
        r = httpx.post(f"{GOV}/api/prepare", json=dict(kind="landing", spec=dict(landing=c["spec"]), candidate_id=candidate_id,
                                                       grid_version=self.ev.version), timeout=10.0)
        self.audit.log("approval_requested", candidate_id=candidate_id, status=r.status_code)
        r.raise_for_status()
        return r.json()

    def request_survey(self, idx: int, alt_m: float = 45.0, sitl_takeoff: bool = False):
        noms = self.plan.get("survey_nominations", [])
        n = noms[idx]
        lat, lon = n["center_latlon"]
        spec = dict(survey=dict(lat=lat, lon=lon, width_m=84.0, length_m=self.plan["required_length_m"] + 40, heading_deg=n["axis_deg"],
                                alt_m=alt_m, spacing_m=14.0, lead_in_m=50.0, sitl_takeoff=sitl_takeoff))
        r = httpx.post(f"{GOV}/api/prepare", json=dict(kind="survey", spec=spec, candidate_id=f"S{idx}", grid_version=self.ev.version),
                       timeout=10.0)
        self.audit.log("survey_requested", idx=idx, status=r.status_code)
        r.raise_for_status()
        return r.json()

    def run(self):
        for fn in (self.frame_loop, self.plan_loop):
            threading.Thread(target=fn, daemon=True).start()


def _inside(pt, poly):
    """Point-in-polygon (lat, lon)."""
    y, x = pt
    inside = False
    n = len(poly)
    for i in range(n):
        y1, x1 = poly[i]
        y2, x2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside
