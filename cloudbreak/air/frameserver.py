"""Read-only HTTP frame server on the Pi (ground PULLS frames; nothing can be written through it).

GET /status              health, capture + bridge stats, Pi boottime (for RTT / link health)
GET /latest.json         newest selected frame metadata
GET /frames?since=N      metadata lines for frames with index >= N (JSON list)
GET /frame/<id>.jpg?w=W  W=1152 (default) preview, W<1152 downscaled preview, W=0 full resolution
GET /tlog?offset=B       raw telemetry log bytes from offset B (post-flight sync)
"""
from __future__ import annotations

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cloudbreak.air import health
from cloudbreak.air.config import load_air_config
from cloudbreak.common.timebase import boottime_ns

FRAME_RE = re.compile(r"^/frame/(f\d{6})\.jpg$")


def make_handler(cfg):
    sdir = Path(cfg["session_dir"])
    shm = Path(cfg["bridge"]["pose_shm"])
    latest = shm.with_name("cloudbreak_latest.json")

    class H(BaseHTTPRequestHandler):
        server_version = "cloudbreak-air/0.1"

        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode())

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/status":
                try:
                    pose = json.loads(shm.read_text())
                except (OSError, ValueError):
                    pose = {}
                try:
                    lat = json.loads(latest.read_text())
                except (OSError, ValueError):
                    lat = {}
                return self._json(dict(t_boot_ns=boottime_ns(), wall=time.time(), session=sdir.name,
                                       health=health.snapshot(str(sdir)), capture=lat.get("stats"),
                                       latest_frame=lat.get("frame_id"), bridge=pose.get("stats"),
                                       clock=pose.get("clock"), pose={k: pose.get(k) for k in
                                                                      ("lat", "lon", "rel_alt", "groundspeed", "fix", "sats", "armed")}))
            if u.path == "/latest.json":
                try:
                    return self._send(200, latest.read_bytes())
                except OSError:
                    return self._json({}, 404)
            if u.path == "/frames":
                since = int(q.get("since", ["0"])[0])
                out = []
                try:
                    with open(sdir / "frames.jsonl") as f:
                        for i, line in enumerate(f):
                            if i >= since:
                                out.append(json.loads(line))
                except OSError:
                    pass
                return self._json(out[:500])
            m = FRAME_RE.match(u.path)
            if m:
                fid = m.group(1)
                w = int(q.get("w", ["1152"])[0])
                p = sdir / ("frames" if w == 0 else "preview") / f"{fid}.jpg"
                if not p.exists():
                    return self._json(dict(error="no such frame"), 404)
                data = p.read_bytes()
                if 0 < w < cfg["camera"]["preview_width"]:
                    import cv2
                    import numpy as np

                    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                    h = int(img.shape[0] * w / img.shape[1])
                    ok, enc = cv2.imencode(".jpg", cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA),
                                           [cv2.IMWRITE_JPEG_QUALITY, 70])
                    data = enc.tobytes()
                return self._send(200, data, "image/jpeg")
            if u.path == "/tlog":
                off = int(q.get("offset", ["0"])[0])
                p = sdir / "telemetry.tlog"
                try:
                    with open(p, "rb") as f:
                        f.seek(off)
                        return self._send(200, f.read(8 << 20), "application/octet-stream")
                except OSError:
                    return self._json({}, 404)
            return self._json(dict(error="not found"), 404)

    return H


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="/etc/cloudbreak/air.toml")
    a = ap.parse_args(argv)
    cfg = load_air_config(a.config)
    srv = ThreadingHTTPServer(("0.0.0.0", int(cfg["frameserver"]["port"])), make_handler(cfg))
    srv.serve_forever()


if __name__ == "__main__":
    main()
