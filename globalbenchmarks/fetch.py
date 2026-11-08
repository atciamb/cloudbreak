"""Scrape the benchmark tiles: orthoimagery + terrain + OpenStreetMap for every site in sites.py.

    .venv\\Scripts\\python -m globalbenchmarks.fetch [--only ID[,ID]] [--category urban,rural] [--force] [--sheet]

Per site -> globalbenchmarks/images/<category>/<id>/
    imagery.jpg   600 x 600 m at 0.5 m/px (1200 px), north-up, centred on the site
    dem.png       1 m/px terrain, 16-bit: elevation_m = offset_m + value * scale_m (see meta.json)
    osm.json.gz   OpenStreetMap features in the box (same Overpass query core's priors use)
    meta.json     georeference, sources, licences, attribution, zoom / native resolution, fetch time
--sheet also writes images/_sheets/imagery_<category>.jpg (raw imagery contact sheets).
Raw tiles are cached in C:\\cb-data\\globalbenchmarks\\tiles, so reruns don't hit the servers again.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import requests

from cloudbreak.common.config import data_dir
from globalbenchmarks.sites import CATEGORIES, GSD_M, OSM_ATTRIBUTION, SOURCES, TERRAIN, Site, Source, select

UA = {"User-Agent": "cloudbreak-globalbenchmarks/0.1 (HackRPI 2026 landing-site research)"}
ROOT = Path(__file__).resolve().parent / "images"
R_EARTH = 6378137.0
ORIGIN = math.pi * R_EARTH
DEM_RES_M = 1.0


def log(*a):
    print("[globalbenchmarks.fetch]", *a, flush=True)


def site_dir(s: Site) -> Path:
    return ROOT / s.category / s.id


# ------------------------------------------------------------------ Web Mercator
def merc(lat: float, lon: float) -> tuple[float, float]:
    return math.radians(lon) * R_EARTH, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R_EARTH


def unmerc(mx: float, my: float) -> tuple[float, float]:
    return math.degrees(2 * math.atan(math.exp(my / R_EARTH)) - math.pi / 2), math.degrees(mx / R_EARTH)


def bbox_3857(s: Site, extent_m: float | None = None) -> tuple[float, float, float, float]:
    """Square ground box centred on the site (default: the site's tile size), in Web Mercator metres (scale 1 / cos(lat))."""
    extent_m = extent_m or s.extent_m
    mx, my = merc(s.lat, s.lon)
    h = extent_m / 2 / math.cos(math.radians(s.lat))
    return mx - h, my - h, mx + h, my + h


def bbox_lonlat(s: Site, extent_m: float | None = None) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox_3857(s, extent_m)
    south, west = unmerc(x0, y0)
    north, east = unmerc(x1, y1)
    return west, south, east, north


def zoom_for(lat: float, gsd_m: float, max_zoom: int) -> int:
    for z in range(10, max_zoom + 1):
        if 2 * ORIGIN / (256 * 2 ** z) * math.cos(math.radians(lat)) <= gsd_m:
            return z
    return max_zoom


def native_res(lat: float, z: int) -> float:
    return 2 * ORIGIN / (256 * 2 ** z) * math.cos(math.radians(lat))


# ------------------------------------------------------------------ HTTP
def _get(url: str, params=None, timeout=60, tries=4, ok_missing=False):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r
            if ok_missing and r.status_code in (204, 404):
                return None
            last = RuntimeError(f"HTTP {r.status_code} for {r.url[:160]}")
        except requests.RequestException as e:  # pragma: no cover - network
            last = e
        time.sleep(1.5 * (i + 1))
    raise last


def _decode(content: bytes, flags=cv2.IMREAD_COLOR) -> np.ndarray | None:
    return cv2.imdecode(np.frombuffer(content, np.uint8), flags)


# ------------------------------------------------------------------ XYZ tiles -> metric square
def xyz_mosaic(src: Source, key: str, bb: tuple, z: int, out_px: int, kind: str = "rgb") -> tuple[np.ndarray, dict]:
    """Fetch the tiles covering the mercator box `bb` at zoom z and resample the box to out_px x out_px."""
    scale = 256 * 2 ** z / (2 * ORIGIN)
    px0, px1 = (bb[0] + ORIGIN) * scale, (bb[2] + ORIGIN) * scale
    py0, py1 = (ORIGIN - bb[3]) * scale, (ORIGIN - bb[1]) * scale
    tx0, tx1, ty0, ty1 = int(px0 // 256), int((px1 - 1e-6) // 256), int(py0 // 256), int((py1 - 1e-6) // 256)
    cache = data_dir() / "globalbenchmarks" / "tiles" / key / str(z)
    ext = "png" if kind == "terrarium" else "jpg"

    def one(txy):
        tx, ty = txy
        f = cache / str(tx) / f"{ty}.{ext}"
        if f.exists():
            data = f.read_bytes()
        else:
            r = _get(src.url.format(z=z, x=tx, y=ty), ok_missing=True)
            if r is None:
                return txy, None
            data = r.content
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        img = _decode(data, cv2.IMREAD_COLOR if kind == "rgb" else cv2.IMREAD_UNCHANGED)
        return txy, img

    tiles = [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]
    with ThreadPoolExecutor(6) as ex:
        got = dict(ex.map(one, tiles))
    canvas = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 3), np.uint8)
    missing = 0
    for (tx, ty), img in got.items():
        if img is None or img.ndim != 3:
            missing += 1
            continue
        canvas[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = img[:256, :256, :3]
    if kind == "terrarium":   # elevation = R*256 + G + B/256 - 32768 (cv2 gives BGR)
        c = canvas.astype(np.float32)
        canvas = (c[..., 2] * 256 + c[..., 1] + c[..., 0] / 256 - 32768).astype(np.float32)
        canvas[canvas < -1000] = np.nan          # missing tile; filled from neighbours by fetch_terrain
    # map output pixel centres into the canvas (sub-pixel exact); pre-blur when shrinking so it doesn't alias
    s = (px1 - px0) / out_px
    if s > 1.2:
        canvas = cv2.resize(canvas, None, fx=1 / s, fy=1 / s, interpolation=cv2.INTER_AREA)
        ox, oy, s = (px0 - tx0 * 256) / s, (py0 - ty0 * 256) / s, 1.0
    else:
        ox, oy = px0 - tx0 * 256, py0 - ty0 * 256
    M = np.array([[s, 0, ox + 0.5 * s - 0.5], [0, s, oy + 0.5 * s - 0.5]], np.float64)
    out = cv2.warpAffine(canvas, M, (out_px, out_px), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                         borderMode=cv2.BORDER_REPLICATE)
    return out, dict(zoom=z, tiles=len(tiles), missing_tiles=missing)


# ------------------------------------------------------------------ ArcGIS ImageServer export (US)
def _chunks(n_px: int, max_piece: int = 600) -> int:
    """Pieces per side for an export: at most ~max_piece px each (the USGS servers 504 on big ones), dividing n evenly."""
    c = max(2, math.ceil(n_px / max_piece))
    while n_px % c:
        c += 1
    return c


def _cached_export(url: str, params: dict) -> bytes:
    """GET an ArcGIS export, cached by its parameters (the USGS servers 502/504 often; retries shouldn't re-download)."""
    import hashlib

    key = hashlib.sha1((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    f = data_dir() / "globalbenchmarks" / "exports" / f"{key}.bin"
    if f.exists():
        return f.read_bytes()
    data = _get(url, params=params, timeout=240, tries=6).content
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return data


def export_image(src: Source, bb: tuple, out_px: int, kind: str = "rgb", chunks: int = 2) -> tuple[np.ndarray, dict]:
    """ArcGIS ImageServer exportImage in chunks x chunks pixel-aligned pieces: the USGS servers time out (504) on big
    single exports. kind 'rgb' -> uint8 BGR image; 'dem' -> float32 elevation (NaN = no data)."""
    n = out_px // chunks
    dx, dy = (bb[2] - bb[0]) / chunks, (bb[3] - bb[1]) / chunks
    out = np.zeros((n * chunks, n * chunks, 3), np.uint8) if kind == "rgb" else np.full((n * chunks, n * chunks), np.nan, np.float32)

    def piece(ij):
        i, j = ij                           # i = row from the north, j = column from the west
        sub = (bb[0] + j * dx, bb[3] - (i + 1) * dy, bb[0] + (j + 1) * dx, bb[3] - i * dy)
        q = dict(bbox=",".join(f"{v:.3f}" for v in sub), bboxSR=3857, imageSR=3857, size=f"{n},{n}", f="image",
                 interpolation="RSP_BilinearInterpolation")
        if kind == "rgb":
            q.update(format="jpg", compressionQuality=92, bandIds="0,1,2")
            im = _decode(_cached_export(src.url, q))
            if im is None:
                raise RuntimeError("export did not return an image")
            return ij, im[:n, :n, :3]
        import rasterio

        q.update(format="tiff", pixelType="F32")
        with rasterio.MemoryFile(_cached_export(src.url, q)) as mf, mf.open() as ds:
            a = ds.read(1).astype(np.float32)[:n, :n]
        a[(a < -500) | (a > 9000)] = np.nan
        return ij, a

    with ThreadPoolExecutor(2) as ex:
        for (i, j), im in ex.map(piece, [(i, j) for i in range(chunks) for j in range(chunks)]):
            out[i * n:(i + 1) * n, j * n:(j + 1) * n] = im
    missing = 0 if kind == "rgb" else int(np.isnan(out).sum())
    return out, dict(zoom=None, tiles=chunks * chunks, missing_tiles=missing)


# ------------------------------------------------------------------ per-site steps
def fetch_imagery(s: Site) -> tuple[np.ndarray, dict]:
    src = SOURCES[s.source]
    n = int(round(s.extent_m / GSD_M))
    bb = bbox_3857(s)
    if src.kind == "export":
        img, info = export_image(src, bb, n, chunks=_chunks(n))
        info["native_res_m"] = 0.3      # NAIP Plus: 0.3 m HRO in many towns, else 0.6 m NAIP, resampled by the server
    else:
        z = zoom_for(s.lat, GSD_M, src.max_zoom)
        img, info = xyz_mosaic(src, s.source, bb, z, n)
        info["native_res_m"] = round(native_res(s.lat, z), 3)
    if info["missing_tiles"]:
        log(f"  WARNING {s.id}: {info['missing_tiles']} imagery tiles missing")
    return img, info


def fetch_terrain(s: Site) -> tuple[np.ndarray, dict]:
    key = s.terrain
    src = TERRAIN[key]
    n = int(round(s.extent_m / DEM_RES_M))
    bb = bbox_3857(s)
    if src.kind == "export":
        try:
            dem, info = export_image(src, bb, n, kind="dem", chunks=_chunks(n))
            info["native_res_m"] = "1-10 (best available 3DEP)"
            info["source"] = key
            return _fill(dem), info
        except Exception as e:  # noqa: BLE001 - the 3DEP server 504s for long stretches
            log(f"  {s.id}: 3DEP unavailable ({e!r:.120}); using terrain tiles (USGS 10 m in the US)")
            key, src = "terrarium", TERRAIN["terrarium"]
    z = src.max_zoom
    dem, info = xyz_mosaic(src, key, bb, z, n, kind="terrarium")
    info["native_res_m"] = f"{native_res(s.lat, z):.1f} m tiles (source DEM ~10-30 m)"
    info["source"] = key
    return _fill(dem), info


def _fill(dem: np.ndarray) -> np.ndarray:
    if np.isnan(dem).any():
        from scipy import ndimage

        idx = ndimage.distance_transform_edt(np.isnan(dem), return_distances=False, return_indices=True)
        dem = dem[tuple(idx)]
    return dem


def save_dem(dem: np.ndarray, path: Path) -> dict:
    lo = float(np.floor(np.nanmin(dem)))
    span = float(np.nanmax(dem)) - lo
    scale = 0.01 if span < 650 else 0.1
    q = np.clip(np.round((dem - lo) / scale), 0, 65535).astype(np.uint16)
    cv2.imwrite(str(path), q)
    return dict(offset_m=lo, scale_m=scale, res_m=DEM_RES_M, min_m=round(float(dem.min()), 2), max_m=round(float(dem.max()), 2))


def load_dem(d: Path, meta: dict) -> np.ndarray:
    q = cv2.imread(str(d / "dem.png"), cv2.IMREAD_UNCHANGED).astype(np.float32)
    t = meta["terrain"]
    return t["offset_m"] + q * t["scale_m"]


_OVERPASS_SLOTS = threading.Semaphore(2)      # Overpass allows ~2 concurrent queries per IP


def fetch_osm(s: Site, margin_m: float = 40.0) -> dict:
    from cloudbreak.ground.core.priors.fetch import OVERPASS_Q   # the exact query core's priors use

    w, so, e, n = bbox_lonlat(s, s.extent_m + 2 * margin_m)
    q = OVERPASS_Q.format(s=so, w=w, n=n, e=e)
    last = None
    with _OVERPASS_SLOTS:
        for attempt in range(3):
            for ep in ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]:
                try:
                    r = requests.post(ep, data={"data": q}, headers=UA, timeout=150)
                    if r.status_code == 200:
                        return r.json()
                    last = RuntimeError(f"{ep}: HTTP {r.status_code}")
                except requests.RequestException as ex:  # pragma: no cover - network
                    last = ex
                time.sleep(5 * (attempt + 1))
    raise last


def fetch_site(s: Site, force: bool = False) -> dict:
    d = site_dir(s)
    meta_f = d / "meta.json"
    if meta_f.exists() and not force:
        log(f"{s.id}: cached")
        return json.loads(meta_f.read_text(encoding="utf-8"))
    d.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    img, iinfo = fetch_imagery(s)
    cv2.imwrite(str(d / "imagery.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    t1 = time.time()
    dem, tinfo = fetch_terrain(s)
    tinfo.update(save_dem(dem, d / "dem.png"))
    t2 = time.time()
    osm = fetch_osm(s)
    log(f"  {s.id}: imagery {t1 - t0:.0f} s, terrain {t2 - t1:.0f} s, osm {time.time() - t2:.0f} s")
    with gzip.open(d / "osm.json.gz", "wt", encoding="utf-8") as f:
        json.dump(osm, f, separators=(",", ":"))
    src, ter = SOURCES[s.source], TERRAIN[tinfo["source"]]          # the terrain actually fetched (3DEP may fall back)
    w, so, e, n = bbox_lonlat(s)
    meta = dict(
        id=s.id, category=s.category, name=s.name, country=s.country, lat=s.lat, lon=s.lon, expect=s.expect, focus=s.focus,
        extent_m=s.extent_m, gsd_m=GSD_M, size_px=img.shape[1], bbox_lonlat=dict(west=w, south=so, east=e, north=n),
        bbox_3857=list(bbox_3857(s)), crs_note="north-up local square; pixel (0,0) = north-west corner",
        imagery=dict(source=s.source, name=src.name, licence=src.licence, attribution=src.attribution, url=src.url, **iinfo),
        terrain=dict(name=ter.name, licence=ter.licence, attribution=ter.attribution, **tinfo),
        osm=dict(elements=len(osm.get("elements", [])), attribution=OSM_ATTRIBUTION,
                 timestamp=osm.get("osm3s", {}).get("timestamp_osm_base")),
        fetched_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        label="BENCHMARK IMAGERY (aerial orthophoto) - not Cloudbreak flight data",
    )
    meta_f.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"{s.id}: z{iinfo.get('zoom')} {iinfo['native_res_m']} m native, {iinfo['tiles']} tiles, DEM {tinfo['min_m']:.0f}-"
        f"{tinfo['max_m']:.0f} m, OSM {meta['osm']['elements']} elements ({time.time() - t0:.0f} s)")
    return meta


# ------------------------------------------------------------------ contact sheets
def put_text(img, txt, org, scale=0.6, color=(255, 255, 255), thick=1, outline=2):
    """Outlined text. The outline is offset copies at the SAME thickness: OpenCV 5's fonts get wider with
    thickness, so a thick black copy underneath would stick out past the text."""
    x, y = org
    for dx in range(-outline, outline + 1):
        for dy in range(-outline, outline + 1):
            if dx or dy:
                cv2.putText(img, txt, (x + dx, y + dy), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick, cv2.LINE_AA)
    cv2.putText(img, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def _label(img, lines, scale=0.9):
    y = 34
    for i, t in enumerate(lines):
        sc = scale if i == 0 else scale * 0.7
        put_text(img, t, (12, y), sc, (255, 255, 255), 2 if i == 0 else 1)
        y += int(34 * sc + 6)


def contact_sheet(paths_and_labels: list[tuple[Path, list[str]]], cols: int = 5, tile: int = 600) -> np.ndarray | None:
    tiles = []
    for p, lines in paths_and_labels:
        im = cv2.imread(str(p))
        if im is None:
            continue
        im = cv2.resize(im, (tile, int(im.shape[0] * tile / im.shape[1])), interpolation=cv2.INTER_AREA)
        _label(im, lines)
        tiles.append(im)
    if not tiles:
        return None
    th = max(t.shape[0] for t in tiles)
    rows = (len(tiles) + cols - 1) // cols
    cols = min(cols, len(tiles))
    sheet = np.full((rows * th + (rows - 1) * 6, cols * tile + (cols - 1) * 6, 3), 30, np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet[r * (th + 6):r * (th + 6) + t.shape[0], c * (tile + 6):c * (tile + 6) + tile] = t
    return sheet


def imagery_sheets(sites: list[Site]) -> list[Path]:
    out = []
    (ROOT / "_sheets").mkdir(parents=True, exist_ok=True)
    for cat in CATEGORIES:
        items = []
        for s in sites:
            if s.category == cat and (site_dir(s) / "meta.json").exists():     # meta.json is written last
                m = json.loads((site_dir(s) / "meta.json").read_text(encoding="utf-8"))
                items.append((site_dir(s) / "imagery.jpg", [f"{s.name} ({s.country})", f"Source: {m['imagery']['name']}"]))
        sheet = contact_sheet(items)
        if sheet is not None:
            p = ROOT / "_sheets" / f"imagery_{cat}.jpg"
            cv2.imwrite(str(p), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
            out.append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated site ids (or substrings)")
    ap.add_argument("--category", help="comma-separated categories")
    ap.add_argument("--force", action="store_true", help="re-fetch even if the site folder exists")
    ap.add_argument("--sheet", action="store_true", help="write raw imagery contact sheets per category")
    ap.add_argument("--workers", type=int, default=3, help="sites fetched in parallel (Overpass is capped at 2)")
    a = ap.parse_args(argv)
    sites = select(a.only, a.category)
    failed = []

    def one(s: Site):
        try:
            fetch_site(s, a.force)
        except Exception as e:  # keep going; report at the end
            failed.append(s.id)
            log(f"{s.id}: FAILED {e!r}")

    with ThreadPoolExecutor(max(1, a.workers)) as ex:
        list(ex.map(one, sites))
    if a.sheet:
        for p in imagery_sheets(select()):
            log("sheet", p)
    log(f"done: {len(sites) - len(failed)}/{len(sites)} ok" + (f", failed: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
