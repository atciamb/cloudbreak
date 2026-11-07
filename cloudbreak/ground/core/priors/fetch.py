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


def fetch_lidar() -> list[dict]:
    items = _tnm_items("Lidar Point Cloud (LPC)")
    keep = []
    for it in items:
        proj = it["title"].split()[4]
        if proj in LIDAR_PROJECTS:
            dest = priors_dir("raw") / "lidar" / proj / Path(it["downloadURL"]).name
            _download(it["downloadURL"], dest)
            keep.append(dict(project=proj, url=it["downloadURL"], path=str(dest), bbox=it["boundingBox"],
                             published=it.get("publicationDate"), bytes=dest.stat().st_size))
    (priors_dir("raw") / "lidar" / "tiles.json").write_text(json.dumps(keep, indent=1))
    log(f"lidar: {len(keep)} tiles, {sum(k['bytes'] for k in keep) / 1e6:.0f} MB")
    return keep


# ------------------------------------------------------------------ DEM (COG windowed read)
def fetch_dem() -> list[dict]:
    """Read only the site window of each 1 m DEM COG, warped onto the 1 m site grid."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT

    g = site_grid(res=1.0)
    out = []
    for it in _tnm_items("Digital Elevation Model (DEM) 1 meter"):
        proj = next((p for p in DEM_PROJECTS if p in it["title"]), None)
        if not proj:
            continue
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


STEPS = dict(osm=fetch_osm, dof=fetch_dof, weather=fetch_weather, dem=fetch_dem, ortho=lambda: (fetch_ortho("2024"), fetch_ortho("2024_cir")),
             lidar=fetch_lidar)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=",".join(STEPS))
    a = ap.parse_args(argv)
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
