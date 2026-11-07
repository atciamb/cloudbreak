"""Download every free prior for the site into C:\\cb-data\\priors\\raw (idempotent, cached).

Run:  .venv\\Scripts\\python -m cloudbreak.ground.core.priors.fetch [--only ortho,lidar,dem,osm,dof,weather]

Sources (all unauthenticated, verified 2026-11-07):
  * NYS GIS Program Office 2024 orthoimagery, 12 in natural colour + CIR (orthos.its.ny.gov MapServer export)
  * USGS 3DEP lidar point clouds via TNM Access API (NY_Hudson_D22 preferred, NY_FEMAR2_Central_2018_D19 fill)
  * USGS 3DEP 1 m DEM COGs (windowed HTTP reads, no full-tile download)
  * OpenStreetMap via Overpass
  * FAA Digital Obstacle File (ArcGIS FeatureServer)
  * Open-Meteo forecast snapshot (wind, gusts, soil moisture, cloud, radiation)
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import requests

from cloudbreak.common.config import priors_dir, site
from cloudbreak.common.geodesy import site_grid

UA = {"User-Agent": "cloudbreak-hackrpi/0.1"}
TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"
LIDAR_PROJECTS = ["NY_Hudson_D22", "NY_FEMAR2_Central_2018_D19"]  # priority order (newest first)
DEM_PROJECTS = ["NY_Hudson_D22", "NY_FEMAR2_Central_2018_D19"]


def log(*a):
    print("[priors.fetch]", *a, flush=True)


def _get(url, params=None, timeout=180, stream=False, tries=4):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout, stream=stream)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code} for {r.url}")
        except requests.RequestException as e:  # pragma: no cover - network
            last = e
        time.sleep(2 * (i + 1))
    raise last


def _download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _get(url, stream=True, timeout=600) as r, open(tmp, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    tmp.replace(dest)
    return dest


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def bbox_str():
    b = site()["bbox"]
    return f"{b['west']},{b['south']},{b['east']},{b['north']}"


# ------------------------------------------------------------------ orthoimagery
def fetch_ortho(service: str = "2024", res: float = 0.3, tile_px: int = 2048) -> list[dict]:
    """Tile the site box in EPSG:32618 at `res` m/px; each tile saved as PNG + JSON georef."""
    from PIL import Image

    g = site_grid()
    xmin, ymin, xmax, ymax = g.bounds
    tile_m = tile_px * res
    out_dir = priors_dir("raw") / f"ortho_{service}"
    out_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://orthos.its.ny.gov/arcgis/rest/services/wms/{service}/MapServer/export"
    tiles = []
    ny = int(np.ceil((ymax - ymin) / tile_m))
    nx = int(np.ceil((xmax - xmin) / tile_m))
    for i in range(ny):
        for j in range(nx):
            x0 = xmin + j * tile_m
            y1 = ymax - i * tile_m
            x1, y0 = x0 + tile_m, y1 - tile_m
            png = out_dir / f"r{i}_c{j}.png"
            meta = dict(service=service, x0=x0, y0=y0, x1=x1, y1=y1, res=res, px=tile_px, crs="EPSG:32618", path=str(png))
            if not png.exists():
                p = dict(bbox=f"{x0},{y0},{x1},{y1}", bboxSR=32618, imageSR=32618, size=f"{tile_px},{tile_px}",
                         format="png32", f="image", transparent="false")
                r = _get(url, params=p)
                im = Image.open(io.BytesIO(r.content))
                if im.size != (tile_px, tile_px):
                    raise RuntimeError(f"unexpected tile size {im.size}")
                im.save(png)
            tiles.append(meta)
    (out_dir / "tiles.json").write_text(json.dumps(dict(source=url, acquired="Spring 2024 (NYS GPO)", tiles=tiles), indent=1))
    log(f"ortho {service}: {len(tiles)} tiles at {res} m")
    return tiles


# ------------------------------------------------------------------ lidar
def _tnm_items(dataset: str) -> list[dict]:
    r = _get(TNM, params=dict(datasets=dataset, bbox=bbox_str(), max=200, outputFormat="JSON"), timeout=120).json()
    return r.get("items", [])


def fetch_lidar(core_radius_m: float = 700.0, workers: int = 6) -> list[dict]:
    """Download LAZ tiles intersecting the core area (field +- core_radius_m), newest project first.
    rockyweb is slow per connection (~4 MB/min observed), so tiles download in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    s = site()["site"]
    dlat = core_radius_m / 111_320.0
    dlon = core_radius_m / (111_320.0 * np.cos(np.radians(s["center_lat"])))
    cb = (s["center_lon"] - dlon, s["center_lat"] - dlat, s["center_lon"] + dlon, s["center_lat"] + dlat)
    sel = []
    for it in _tnm_items("Lidar Point Cloud (LPC)"):
        proj = it["title"].split()[4]
        bb = it["boundingBox"]
        hit = not (bb["maxX"] < cb[0] or bb["minX"] > cb[2] or bb["maxY"] < cb[1] or bb["minY"] > cb[3])
        if proj in LIDAR_PROJECTS and hit:
            sel.append((LIDAR_PROJECTS.index(proj), proj, it))
    sel.sort(key=lambda t: t[0])

    def one(t):
        _, proj, it = t
        dest = priors_dir("raw") / "lidar" / proj / Path(it["downloadURL"]).name
        _download(it["downloadURL"], dest)
        log("lidar tile", dest.name, f"{dest.stat().st_size / 1e6:.0f} MB")
        return dict(project=proj, url=it["downloadURL"], path=str(dest), bbox=it["boundingBox"],
                    published=it.get("publicationDate"), bytes=dest.stat().st_size)

    with ThreadPoolExecutor(workers) as ex:
        keep = list(ex.map(one, sel))
    (priors_dir("raw") / "lidar" / "tiles.json").write_text(json.dumps(keep, indent=1))
    log(f"lidar: {len(keep)} tiles, {sum(k['bytes'] for k in keep) / 1e6:.0f} MB")
    return keep


# ------------------------------------------------------------------ lidar via Entwine Point Tiles on AWS (fast)
EPT_ROOT = "https://s3-us-west-2.amazonaws.com/usgs-lidar-public"


def _collection_year(name: str, pub: str = "") -> int:
    """Best-effort acquisition year from a USGS project/work-unit name (..._2018..., ..._D22 -> 2022)."""
    import re

    m = re.findall(r"(20\d\d)", name)
    if m:
        return int(m[-1])
    m = re.search(r"_D(\d\d)$", name) or re.search(r"_D(\d\d)_", name)
    if m:
        return 2000 + int(m.group(1))
    return int(pub[:4]) if pub[:4].isdigit() else 0


def lidar_workunits(core_radius_m: float = 700.0) -> list[str]:
    """LPC work units ranked by how much of the CORE area (site centre +- core_radius_m) their tiles cover,
    then by collection year (newest first). A newer survey that only clips the edge of the box loses to an
    older one that covers the field. (EPT names = work-unit names.)"""
    s = site()["site"]
    dlat = core_radius_m / 111_320.0
    dlon = core_radius_m / (111_320.0 * np.cos(np.radians(s["center_lat"])))
    core = (s["center_lon"] - dlon, s["center_lat"] - dlat, s["center_lon"] + dlon, s["center_lat"] + dlat)
    core_area = (core[2] - core[0]) * (core[3] - core[1])
    seen: dict[str, dict] = {}
    for it in _tnm_items("Lidar Point Cloud (LPC)"):
        parts = it["downloadURL"].split("/")
        if "Projects" not in parts:
            continue
        i = parts.index("Projects")
        proj, wu = parts[i + 1], parts[i + 2]
        if wu == "LAZ":
            wu = proj
        bb = it["boundingBox"]
        ix = max(0.0, min(bb["maxX"], core[2]) - max(bb["minX"], core[0]))
        iy = max(0.0, min(bb["maxY"], core[3]) - max(bb["minY"], core[1]))
        r = seen.setdefault(wu, dict(year=_collection_year(wu, it.get("publicationDate") or ""), cover=0.0))
        r["cover"] = min(1.0, r["cover"] + ix * iy / core_area)
    ranked = sorted(seen.items(), key=lambda kv: (-int(kv[1]["cover"] >= 0.6), -kv[1]["year"], -float(kv[1]["cover"])))
    log("lidar work units (core coverage, year):", [(w, round(r["cover"], 2), r["year"]) for w, r in ranked])
    return [w for w, _ in ranked]


def ept_projects(max_n: int = 2) -> list[str]:
    """Newest work units that have an Entwine (EPT) copy on AWS, cached per site in raw/ept/order.json."""
    f = priors_dir("raw") / "ept" / "order.json"
    if f.exists():
        return json.loads(f.read_text())
    out = []
    for wu in lidar_workunits():
        try:
            r = requests.head(f"{EPT_ROOT}/{wu}/ept.json", headers=UA, timeout=20)
            if r.status_code == 200:
                out.append(wu)
        except requests.RequestException:
            pass
        if len(out) >= max_n:
            break
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out))
    log("ept work units (newest first):", out)
    return out


EPT_PROJECTS = ["NY_Hudson_1_D22", "NY_FEMAR2_Central_4_2018"]  # legacy '86 Field order (kept for reference)


def fetch_ept(core_radius_m: float = 700.0, workers: int = 16, max_depth: int = 20) -> list[dict]:
    """Download every EPT octree node (all depths) that intersects the core box around the field.
    The union of nodes over all depths is the full-density point cloud for that box."""
    from concurrent.futures import ThreadPoolExecutor

    from cloudbreak.common.geodesy import _tf

    s = site()["site"]
    tf = _tf("EPSG:4326", "EPSG:3857")
    cx, cy = tf.transform(s["center_lon"], s["center_lat"])
    k = 1.0 / np.cos(np.radians(s["center_lat"]))          # web-mercator scale factor
    r = core_radius_m * k
    box = (cx - r, cy - r, cx + r, cy + r)
    out = []
    for name in ept_projects():
        meta = _get(f"{EPT_ROOT}/{name}/ept.json").json()
        b = meta["bounds"]
        size0 = b[3] - b[0]

        def node_box(key):
            d, x, y, _ = map(int, key.split("-"))
            sz = size0 / (2 ** d)
            return (b[0] + x * sz, b[1] + y * sz, b[0] + (x + 1) * sz, b[1] + (y + 1) * sz)

        def hits(key):
            nb = node_box(key)
            return not (nb[2] < box[0] or nb[0] > box[2] or nb[3] < box[1] or nb[1] > box[3])

        nodes, pending = {}, ["0-0-0-0"]
        while pending:
            hk = pending.pop()
            h = _get(f"{EPT_ROOT}/{name}/ept-hierarchy/{hk}.json").json()
            for key, cnt in h.items():
                if int(key.split("-")[0]) > max_depth or not hits(key):
                    continue
                if cnt == -1:
                    pending.append(key)
                elif cnt > 0:
                    nodes[key] = cnt
        dest_dir = priors_dir("raw") / "ept" / name
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "ept.json").write_text(json.dumps(meta))

        def one(key):
            return _download(f"{EPT_ROOT}/{name}/ept-data/{key}.laz", dest_dir / f"{key}.laz")

        with ThreadPoolExecutor(workers) as ex:
            files = list(ex.map(one, sorted(nodes)))
        tot = sum(f.stat().st_size for f in files)
        info = dict(project=name, nodes=len(nodes), points=int(sum(nodes.values())), bytes=tot, box3857=box,
                    max_depth=max(int(k.split("-")[0]) for k in nodes) if nodes else None, dir=str(dest_dir))
        (dest_dir / "nodes.json").write_text(json.dumps(dict(info=info, nodes=nodes)))
        log(f"ept {name}: {len(nodes)} nodes, {info['points'] / 1e6:.1f} M pts, {tot / 1e6:.0f} MB, depth<={info['max_depth']}")
        out.append(info)
    return out


# ------------------------------------------------------------------ DEM (COG windowed read)
def fetch_dem() -> list[dict]:
    """Read only the site window of each 1 m DEM COG, warped onto the 1 m site grid."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT

    g = site_grid(res=1.0)
    out = []
    items = []
    for it in _tnm_items("Digital Elevation Model (DEM) 1 meter"):
        proj = it["downloadURL"].split("/Projects/")[1].split("/")[0] if "/Projects/" in it["downloadURL"] else it["title"]
        items.append((_collection_year(proj, it.get("publicationDate") or ""), proj, it))
    items.sort(key=lambda t: -t[0])
    (priors_dir("raw") / "dem").mkdir(parents=True, exist_ok=True)
    (priors_dir("raw") / "dem" / "order.json").write_text(json.dumps([p for _, p, _ in items]))
    for _, proj, it in items:
        dest = priors_dir("raw") / "dem" / f"dem1m_{proj}.tif"
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.Env(GDAL_HTTP_USERAGENT=UA["User-Agent"], GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
                with rasterio.open("/vsicurl/" + it["downloadURL"]) as src:
                    with WarpedVRT(src, crs=g.crs, transform=g.transform, width=g.width, height=g.height,
                                   resampling=Resampling.bilinear, src_nodata=src.nodata, nodata=np.nan) as vrt:
                        a = vrt.read(1, out_dtype="float32")
                        src_crs = str(src.crs)
            prof = dict(driver="GTiff", dtype="float32", count=1, width=g.width, height=g.height, crs=g.crs,
                        transform=g.transform, nodata=np.nan, compress="deflate", tiled=True)
            with rasterio.open(dest, "w", **prof) as dst:
                dst.write(a, 1)
                dst.update_tags(source=it["downloadURL"], src_crs=src_crs, vertical="NAVD88 (m)")
        out.append(dict(project=proj, url=it["downloadURL"], path=str(dest)))
    log(f"dem: {len(out)} windows")
    return out


# ------------------------------------------------------------------ OSM
OVERPASS_Q = """[out:json][timeout:120][bbox:{s},{w},{n},{e}];
(nwr[power~"^(line|minor_line|cable|tower|pole|portal|substation)$"];
 nwr[building];
 nwr[natural~"^(tree|tree_row|wood|water|scrub|wetland)$"];
 nwr[landuse~"^(forest|grass|meadow|construction)$"];
 nwr[waterway];
 nwr[barrier~"^(fence|wall|hedge|retaining_wall|guard_rail)$"];
 nwr[leisure~"^(pitch|track|stadium|park|playground)$"];
 nwr[highway];
 nwr[amenity~"^(parking|bench)$"];
 nwr[man_made~"^(mast|tower|flagpole|antenna|chimney|street_cabinet)$"];
 nwr[sport];
);
out geom;"""


def fetch_osm() -> Path:
    dest = priors_dir("raw") / "osm.json"
    if dest.exists():
        return dest
    b = site()["bbox"]
    q = OVERPASS_Q.format(s=b["south"], w=b["west"], n=b["north"], e=b["east"])
    for ep in ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]:
        try:
            r = requests.post(ep, data={"data": q}, headers=UA, timeout=240)
            if r.status_code == 200:
                dest.write_bytes(r.content)
                log(f"osm: {len(r.json().get('elements', []))} elements from {ep}")
                return dest
        except requests.RequestException as e:  # pragma: no cover
            log("overpass failed", ep, e)
    raise RuntimeError("Overpass unavailable")


# ------------------------------------------------------------------ FAA DOF
def fetch_dof() -> Path:
    dest = priors_dir("raw") / "faa_dof.json"
    if dest.exists():
        return dest
    b = site()["bbox"]
    url = "https://services6.arcgis.com/ssFJjBXIUyZDrSYZ/arcgis/rest/services/Digital_Obstacle_File/FeatureServer/0/query"
    p = dict(geometry=f"{b['west'] - 0.02},{b['south'] - 0.02},{b['east'] + 0.02},{b['north'] + 0.02}",
             geometryType="esriGeometryEnvelope", inSR=4326, outSR=4326, outFields="*", f="json")
    dest.write_bytes(_get(url, params=p).content)
    log(f"faa dof: {len(json.loads(dest.read_text()).get('features', []))} obstacles")
    return dest


# ------------------------------------------------------------------ weather snapshot
def fetch_weather() -> Path:
    s = site()["site"]
    stamp = time.strftime("%Y%m%dT%H%M")
    dest = priors_dir("raw") / "weather" / f"openmeteo_{stamp}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    p = dict(latitude=s["center_lat"], longitude=s["center_lon"],
             hourly="wind_speed_10m,wind_direction_10m,wind_gusts_10m,wind_speed_80m,wind_direction_80m,wind_speed_120m,"
                    "soil_moisture_0_to_1cm,precipitation,snow_depth,cloud_cover,shortwave_radiation,visibility,temperature_2m,"
                    "surface_pressure",
             minutely_15="wind_speed_10m,wind_direction_10m,wind_gusts_10m,wind_speed_80m,visibility,precipitation",
             past_days=3, forecast_days=2, wind_speed_unit="ms", timezone="America/New_York")
    dest.write_bytes(_get("https://api.open-meteo.com/v1/forecast", params=p).content)
    log("weather snapshot", dest.name)
    return dest


STEPS = dict(osm=fetch_osm, dof=fetch_dof, weather=fetch_weather, dem=fetch_dem, ortho=lambda: (fetch_ortho(_ortho_year()), fetch_ortho(_ortho_year() + "_cir")),
             ept=fetch_ept, lidar=fetch_lidar)


def _ortho_year() -> str:
    return str(site().get("priors", {}).get("ortho_year", "2024"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="osm,dof,weather,dem,ortho,ept")   # 'lidar' (rockyweb tiles) is slow; EPT replaces it
    ap.add_argument("--site", default=None, help="site key (config/site_<key>.toml); default CLOUDBREAK_SITE or 86field")
    a = ap.parse_args(argv)
    if a.site:
        from cloudbreak.common.config import set_site

        set_site(a.site)
    log("site:", site()["site"]["name"], "->", priors_dir())
    status = {}
    for name in a.only.split(","):
        t0 = time.time()
        try:
            STEPS[name]()
            status[name] = f"ok ({time.time() - t0:.0f}s)"
        except Exception as e:  # keep going: each prior is optional except where the planner says otherwise
            status[name] = f"FAILED: {e!r}"
        log(name, status[name])
    (priors_dir("raw") / "fetch_status.json").write_text(json.dumps(status, indent=1))
    return 0 if all(v.startswith("ok") for v in status.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
