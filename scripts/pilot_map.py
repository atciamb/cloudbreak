"""Pilot's map of Schuyler Flatts for the Sunday flights (F1 maiden, F2 AUTO survey).

    .venv\\Scripts\\python scripts\\pilot_map.py [--out docs/field/schuyler_pilot_map.jpg]

Draws on aerial imagery (Esri World Imagery tiles, fetched at run time):
  * the geofence uploaded to the FC (config/site_schuyler.toml [fence]): crossing it = automatic RTL
  * the 20 m margin every planned AUTO path keeps inside the fence (planner + governor)
  * where to arm and launch: home = the arming spot, and RTL circles home at 50 m, so home must sit at least
    the flown RTL radius (~70 m at the default WP_LOITER_RAD 60, ~50 m at 40) plus a margin inside the fence
  * a suggested launch/home spot on open grass (picked from the imagery; the fence's centre is among trees)
  * the Open-Meteo wind forecast for the morning of Sun 8 Nov 2026 (fetched 7 Nov, ~19:00)
"""
from __future__ import annotations

import argparse
import io
import math
import sys
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Point, Polygon

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudbreak.common.config import load_toml  # noqa: E402
from cloudbreak.common.geodesy import lonlat_to_utm, utm_to_lonlat  # noqa: E402

Z = 18                       # tile zoom, ~0.44 m/px here
RTL_ZONE_M = 75.0            # launch zone: at least this far inside the fence
RTL_CIRCLE_M = 70.0          # flown RTL circle drawn around home (default loiter radius)
HOME = (42.705419, -73.711520)
LABELS = [((42.704730, -73.708838), "wooded strip\n+ creek"), ((42.705203, -73.710340), "scattered\ntrees"),
          ((42.705991, -73.707121), "I-787")]
TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
WHITE, BLACK = (255, 255, 255, 255), (0, 0, 0, 255)


def ll2px(lat: float, lon: float) -> tuple[float, float]:
    n = 2 ** Z * 256
    x = (lon + 180.0) / 360.0 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def dashed(d: ImageDraw.ImageDraw, pts, fill, width, dash=14, gap=10):
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        length = math.hypot(xb - xa, yb - ya)
        t = 0.0
        while t < length:
            t2 = min(length, t + dash)
            d.line([(xa + (xb - xa) * t / length, ya + (yb - ya) * t / length),
                    (xa + (xb - xa) * t2 / length, ya + (yb - ya) * t2 / length)], fill=fill, width=width)
            t += dash + gap


def fetch_imagery(x0, y0, x1, y1) -> Image.Image:
    tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (60, 60, 60))
    sess = requests.Session()
    sess.headers["User-Agent"] = "cloudbreak-pilot-map/1.0"
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            r = sess.get(TILES.format(z=Z, y=ty, x=tx), timeout=20)
            if r.ok and r.headers.get("content-type", "").startswith("image"):
                mosaic.paste(Image.open(io.BytesIO(r.content)).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
    return mosaic.crop((int(x0 - tx0 * 256), int(y0 - ty0 * 256), int(x1 - tx0 * 256), int(y1 - ty0 * 256)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/field/schuyler_pilot_map.jpg")
    a = ap.parse_args(argv)

    s = load_toml("site_schuyler.toml")
    fence = Polygon([lonlat_to_utm(lo, la) for la, lo in s["fence"]["polygon"]])
    inner20 = fence.buffer(-float(s["fence"].get("path_margin_m", 20.0)))
    zone = fence.buffer(-RTL_ZONE_M)
    home = Point(*lonlat_to_utm(HOME[1], HOME[0]))
    print(f"home {HOME[0]:.6f},{HOME[1]:.6f}: inside launch zone {zone.contains(home)}, "
          f"{fence.exterior.distance(home):.0f} m from the nearest fence edge")

    minx, miny, maxx, maxy = fence.bounds
    lo0, la0 = utm_to_lonlat(minx - 140, maxy + 140)
    lo1, la1 = utm_to_lonlat(maxx + 140, miny - 140)
    ox, oy = ll2px(la0, lo0)
    x1, y1 = ll2px(la1, lo1)
    img = fetch_imagery(ox, oy, x1, y1)
    W, H = img.size
    m_per_px = 156543.03392 * math.cos(math.radians(HOME[0])) / 2 ** Z

    def px_ll(lat, lon):
        x, y = ll2px(lat, lon)
        return x - ox, y - oy

    def px_utm(x, y):
        lon, lat = utm_to_lonlat(x, y)
        return px_ll(lat, lon)

    def rings(geom):
        return [[px_utm(x, y) for x, y in g.exterior.coords] for g in getattr(geom, "geoms", [geom]) if not g.is_empty]

    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for r in rings(zone):
        d.polygon(r, fill=(40, 220, 90, 70), outline=(40, 230, 90, 255))
    for r in rings(inner20):
        dashed(d, r, (255, 190, 0, 255), 3)
    for r in rings(fence):
        d.line(r, fill=(255, 40, 40, 255), width=5)
    hx, hy = px_ll(*HOME)
    rr = RTL_CIRCLE_M / m_per_px
    dashed(d, [(hx + rr * math.cos(k / 60 * 2 * math.pi), hy + rr * math.sin(k / 60 * 2 * math.pi)) for k in range(61)],
           (0, 230, 255, 255), 3, 10, 7)
    d.ellipse([hx - 9, hy - 9, hx + 9, hy + 9], fill=WHITE, outline=BLACK, width=2)
    d.text((hx + 14, hy - 12), "suggested launch / home\n(open grass: confirm on site)", font=font(20, True), fill=WHITE,
           stroke_width=3, stroke_fill=BLACK, spacing=3)
    for (lat, lon), txt in LABELS:
        d.text(px_ll(lat, lon), txt, font=font(20, True), fill=(255, 235, 120, 255), stroke_width=3, stroke_fill=BLACK,
               spacing=3)

    nx, ny = W - 70, 90                                                     # north arrow
    d.polygon([(nx, ny - 45), (nx - 16, ny + 5), (nx + 16, ny + 5)], fill=(255, 255, 255, 230), outline=BLACK)
    d.text((nx - 9, ny + 8), "N", font=font(28, True), fill=WHITE, stroke_width=3, stroke_fill=BLACK)
    sb = 100.0 / m_per_px                                                   # scale bar
    sx, sy = W - 60 - sb, H - 60
    d.rectangle([sx, sy, sx + sb, sy + 10], fill=WHITE, outline=BLACK, width=2)
    d.text((sx + sb / 2 - 28, sy - 30), "100 m", font=font(22, True), fill=WHITE, stroke_width=3, stroke_fill=BLACK)

    def wind_arrow(cx, cy, from_deg, color, label):
        """Arrow points the way the wind BLOWS (downwind)."""
        to = math.radians(from_deg + 180.0)
        ex, ey = cx + 34 * math.sin(to), cy - 34 * math.cos(to)
        d.line([(cx - 34 * math.sin(to), cy + 34 * math.cos(to)), (ex, ey)], fill=color, width=7)
        a1, a2 = to + math.radians(150), to - math.radians(150)
        d.polygon([(ex, ey), (ex + 20 * math.sin(a1), ey - 20 * math.cos(a1)),
                   (ex + 20 * math.sin(a2), ey - 20 * math.cos(a2))], fill=color)
        d.text((cx + 56, cy - 24), label, font=font(19, True), fill=WHITE, spacing=4)

    lx, ly = 18, 18                                                         # legend
    d.rounded_rectangle([lx, ly, lx + 580, ly + 470], 12, fill=(0, 0, 0, 175))
    f = font(19)
    d.text((lx + 16, ly + 12), "Schuyler Flatts - pilot map (Sun 8 Nov)", font=font(24, True), fill=WHITE)
    y = ly + 54
    d.line([(lx + 18, y + 11), (lx + 70, y + 11)], fill=(255, 40, 40, 255), width=5)
    d.text((lx + 82, y), "Geofence on the FC: crossing it = automatic RTL", font=f, fill=WHITE)
    y += 32
    dashed(d, [(lx + 18, y + 11), (lx + 70, y + 11)], (255, 190, 0, 255), 3, 10, 6)
    d.text((lx + 82, y), "AUTO missions stay inside this (20 m margin)", font=f, fill=WHITE)
    y += 32
    d.rectangle([lx + 18, y + 2, lx + 70, y + 20], fill=(40, 220, 90, 110), outline=(40, 230, 90, 255))
    d.text((lx + 82, y), f"Arm + launch here (>= {RTL_ZONE_M:.0f} m inside):", font=f, fill=WHITE)
    d.text((lx + 82, y + 24), "home = arming spot; RTL circles home at 50 m", font=f, fill=WHITE)
    y += 56
    dashed(d, [(lx + 18, y + 11), (lx + 70, y + 11)], (0, 230, 255, 255), 3, 8, 5)
    d.text((lx + 82, y), f"~{RTL_CIRCLE_M:.0f} m RTL circle (default loiter radius)", font=f, fill=WHITE)
    y += 40
    d.text((lx + 16, y), "Forecast wind (Open-Meteo, 10 m); arrows point downwind:", font=font(21, True), fill=WHITE)
    wind_arrow(lx + 60, y + 66, 120, (120, 220, 255, 255), "06:00-08:00  from SE, ~1 m/s\nlaunch + land heading SE (into wind)")
    wind_arrow(lx + 60, y + 142, 300, (255, 150, 60, 255), "from ~09:00  from WNW, 3-4 m/s\nlaunch + land heading WNW")
    d.text((lx + 16, y + 192), "Gusts 8-11 m/s forecast all morning:\ncheck on site (METAR KALB) before go/no-go",
           font=font(19, True), fill=(255, 220, 80, 255), spacing=4)
    d.text((10, H - 28), "Imagery: Esri World Imagery (Esri, Maxar, Earthstar Geographics). Fence: config/site_schuyler.toml. "
           "Not a legal chart.", font=font(16), fill=WHITE, stroke_width=2, stroke_fill=BLACK)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB").save(out, quality=85, optimize=True)
    print(f"{out} {W}x{H} {out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
