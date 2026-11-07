"""Rasterize cached priors onto the shared 0.5 m EPSG:32618 site grid.

Run:  .venv\\Scripts\\python -m cloudbreak.ground.core.priors.build_layers [--skip-lidar]

Outputs (C:\\cb-data\\priors\\layers):
  ortho_hr.tif (0.3 m RGB, renderer texture) ortho_rgb.tif ortho_nir.tif ndvi.tif
  dtm.tif dsm.tif hag.tif slope.tif lidar_class.tif lidar_count.tif
  osm_*.tif hazard_buffer.tif prior_class.tif prior_conf.tif obstacles.geojson manifest.json quicklook/*.png

Conventions: heights in metres NAVD88 (DTM/DSM), HAG = DSM - DTM >= 0. Prior class ids follow
cloudbreak.common.classes. The prior is deliberately weak: it may *rule out* cells (buildings, water,
trees, wires) and nominate survey areas, but it can never make a cell "safe" on its own.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.warp import reproject
from scipy import ndimage
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import transform as shp_transform

from cloudbreak.common.classes import IDX
from cloudbreak.common.config import priors_dir, site
from cloudbreak.common.geodesy import Grid, _tf, site_grid

RAW = priors_dir("raw")
OUT = priors_dir("layers")


def log(*a):
    print("[priors.build]", *a, flush=True)


def write(name: str, arr: np.ndarray, g: Grid, nodata=None, tags: dict | None = None, dtype=None):
    arr = np.asarray(arr)
    if arr.ndim == 2:
        arr = arr[None]
    dtype = dtype or arr.dtype
    prof = dict(driver="GTiff", dtype=dtype, count=arr.shape[0], width=g.width, height=g.height, crs=g.crs,
                transform=g.transform, compress="deflate", tiled=True, blockxsize=512, blockysize=512, BIGTIFF="IF_SAFER")
    if nodata is not None:
        prof["nodata"] = nodata
    p = OUT / f"{name}.tif"
    with rasterio.open(p, "w", **prof) as dst:
        dst.write(arr.astype(dtype))
        if tags:
            dst.update_tags(**{k: str(v) for k, v in tags.items()})
    return p


def read(name: str):
    with rasterio.open(OUT / f"{name}.tif") as src:
        a = src.read()
        return a[0] if a.shape[0] == 1 else a


def resample(src_arr, src_grid: Grid, dst_grid: Grid, method=Resampling.bilinear, nodata=np.nan):
    bands = src_arr if src_arr.ndim == 3 else src_arr[None]
    out = np.full((bands.shape[0], dst_grid.height, dst_grid.width), nodata, dtype=np.float32)
    for b in range(bands.shape[0]):
        reproject(bands[b].astype(np.float32), out[b], src_transform=src_grid.transform, src_crs=src_grid.crs,
                  dst_transform=dst_grid.transform, dst_crs=dst_grid.crs, resampling=method,
                  src_nodata=nodata, dst_nodata=nodata)
    return out if src_arr.ndim == 3 else out[0]


# ------------------------------------------------------------------ ortho
def build_ortho(g: Grid):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    res_hr = 0.3
    ghr = Grid(g.x0, g.y0, res_hr, int(round(g.width * g.res / res_hr)), int(round(g.height * g.res / res_hr)))
    mos = {}
    for svc in ("2024", "2024_cir"):
        meta = json.loads((RAW / f"ortho_{svc}" / "tiles.json").read_text())
        canvas = np.zeros((3, ghr.height, ghr.width), np.uint8)
        for t in meta["tiles"]:
            a = np.array(Image.open(t["path"]).convert("RGB")).transpose(2, 0, 1)
            c0 = int(round((t["x0"] - ghr.x0) / res_hr))
            r0 = int(round((ghr.y0 - t["y1"]) / res_hr))
            h, w = a.shape[1:]
            rs, cs = max(0, r0), max(0, c0)
            re_, ce = min(ghr.height, r0 + h), min(ghr.width, c0 + w)
            if re_ > rs and ce > cs:
                canvas[:, rs:re_, cs:ce] = a[:, rs - r0:re_ - r0, cs - c0:ce - c0]
        mos[svc] = canvas
    write("ortho_hr", mos["2024"], ghr, tags=dict(source="NYS GPO 2024 natural colour, 12in", res=res_hr))
    rgb = resample(mos["2024"].astype(np.float32), ghr, g, Resampling.average, nodata=-1)
    cir = resample(mos["2024_cir"].astype(np.float32), ghr, g, Resampling.average, nodata=-1)
    nir = cir[0]  # CIR band order: NIR, Red, Green
    red = rgb[0]
    ndvi = np.where((nir + red) > 0, (nir - red) / np.maximum(nir + red, 1), np.nan).astype(np.float32)
    write("ortho_rgb", np.clip(rgb, 0, 255).astype(np.uint8), g, tags=dict(source="NYS GPO 2024"))
    write("ortho_nir", np.clip(nir, 0, 255).astype(np.uint8), g, tags=dict(source="NYS GPO 2024 CIR band 1"))
    write("ndvi", ndvi, g, nodata=np.nan, tags=dict(note="from 8-bit display-stretched CIR; relative only, spring (likely leaf-off)"))
    log("ortho/ndvi done", ghr.shape)


# ------------------------------------------------------------------ DEM
def build_dtm(g: Grid):
    g1 = site_grid(res=1.0)
    dtm1 = np.full(g1.shape, np.nan, np.float32)
    used = []
    for proj in ("NY_Hudson_D22", "NY_FEMAR2_Central_2018_D19"):   # priority order
        p = RAW / "dem" / f"dem1m_{proj}.tif"
        if not p.exists():
            continue
        with rasterio.open(p) as src:
            a = src.read(1).astype(np.float32)
        a[(a < -100) | (a > 2000)] = np.nan
        fill = np.isnan(dtm1) & ~np.isnan(a)
        dtm1[fill] = a[fill]
        used.append(dict(project=proj, cells=int(fill.sum())))
    # fill any remaining holes by nearest valid
    if np.isnan(dtm1).any():
        idx = ndimage.distance_transform_edt(np.isnan(dtm1), return_distances=False, return_indices=True)
        dtm1 = dtm1[tuple(idx)]
    dtm = resample(dtm1, g1, g, Resampling.bilinear)
    write("dtm", dtm, g, nodata=np.nan, tags=dict(source="USGS 3DEP 1m DEM", vertical="NAVD88 m", projects=json.dumps(used)))
    # slope (deg) on lightly smoothed DTM
    sm = ndimage.gaussian_filter(dtm, 1.0)
    gy, gx = np.gradient(sm, g.res)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
    write("slope", slope, g, tags=dict(units="deg"))
    log("dtm/slope done", used)
    return dtm


# ------------------------------------------------------------------ lidar
def _lidar_vertical_scale(crs) -> float:
    try:
        if crs is not None and crs.is_compound:
            vert = crs.sub_crs_list[1]
            u = vert.axis_info[0].unit_name.lower()
            if "foot" in u or "feet" in u:
                return 0.3048006096 if "us" in u else 0.3048
    except Exception:
        pass
    return 1.0


def build_lidar(g: Grid, dtm: np.ndarray):
    import laspy

    tiles = json.loads((RAW / "lidar" / "tiles.json").read_text())
    order = {"NY_Hudson_D22": 0, "NY_FEMAR2_Central_2018_D19": 1}
    tiles.sort(key=lambda t: order.get(t["project"], 9))
    H, W = g.shape
    dsm = np.full(H * W, -np.inf, np.float32)
    count = np.zeros(H * W, np.uint16)
    # class priority: building 6 > high veg 5 > med veg 4 > low veg 3 > water 9 > ground 2 > other
    prio = np.zeros(256, np.uint8)
    for c, p in {6: 6, 5: 5, 4: 4, 3: 3, 9: 2, 2: 1, 14: 7, 15: 7}.items():   # 14 wire conductor, 15 tower
        prio[c] = p
    cls_best = np.zeros(H * W, np.uint8)
    covered_by = np.full(H * W, 255, np.uint8)   # project rank that covered the cell first
    xmin, ymin, xmax, ymax = g.bounds
    info = []
    for t in tiles:
        rank = order.get(t["project"], 9)
        with laspy.open(t["path"]) as f:
            crs = f.header.parse_crs()
            vscale = _lidar_vertical_scale(crs)
            tf = _tf(crs.to_wkt() if crs is not None else "EPSG:6347", g.crs)
            npts = 0
            for pts in f.chunk_iterator(3_000_000):
                x, y = tf.transform(np.asarray(pts.x), np.asarray(pts.y))
                z = np.asarray(pts.z, dtype=np.float64) * vscale
                cls = np.asarray(pts.classification, dtype=np.uint8)
                ok = (x >= xmin) & (x < xmax) & (y > ymin) & (y <= ymax) & (cls != 7) & (cls != 18)  # drop noise
                if not ok.any():
                    continue
                c = ((x[ok] - xmin) / g.res).astype(np.int64)
                r = ((ymax - y[ok]) / g.res).astype(np.int64)
                lin = r * W + c
                # newer project wins where it has data: skip cells already covered by a better-ranked project
                keep = covered_by[lin] >= rank
                lin, zz, cc = lin[keep], z[ok][keep].astype(np.float32), cls[ok][keep]
                np.maximum.at(dsm, lin, zz)
                np.add.at(count, lin, 1)
                pr = prio[cc]
                cur = prio[cls_best[lin]]
                upd = pr > cur
                # resolve duplicates: process in priority order
                order_idx = np.argsort(pr[upd], kind="stable")
                cls_best[lin[upd][order_idx]] = cc[upd][order_idx]
                covered_by[lin] = np.minimum(covered_by[lin], rank)
                npts += int(keep.sum())
            info.append(dict(project=t["project"], file=Path(t["path"]).name, points_used=npts, vscale=vscale,
                             crs=crs.name if crs is not None else None))
            log("lidar", Path(t["path"]).name, npts, "pts")
    dsm = dsm.reshape(H, W)
    count = count.reshape(H, W)
    cls_best = cls_best.reshape(H, W)
    empty = ~np.isfinite(dsm)
    # conservative gap fill: 3x3 max of neighbours (obstacles grow, never shrink), then DTM for true voids (water)
    dsm_f = np.where(empty, -np.inf, dsm)
    dil = ndimage.maximum_filter(dsm_f, size=3)
    dsm = np.where(empty, dil, dsm)
    still = ~np.isfinite(dsm)
    dsm[still] = dtm[still]
    dsm = np.maximum(dsm, dtm)
    hag = np.clip(dsm - dtm, 0, 120).astype(np.float32)
    write("dsm", dsm.astype(np.float32), g, nodata=np.nan, tags=dict(source="USGS 3DEP LPC max-z", vertical="NAVD88 m",
                                                                     tiles=json.dumps(info)[:30000]))
    write("hag", hag, g, tags=dict(note="DSM-DTM, 3x3 max gap fill (conservative)"))
    write("lidar_class", cls_best, g, dtype="uint8", tags=dict(note="ASPRS class with priority building>veg>water>ground"))
    write("lidar_count", count, g, dtype="uint16")
    log("lidar layers done; empty cells before fill:", int(empty.sum()))
    return hag, cls_best


# ------------------------------------------------------------------ OSM
def _osm_geoms():
    data = json.loads((RAW / "osm.json").read_text())
    tf = _tf("EPSG:4326", "EPSG:32618")
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        geom = None
        if el["type"] == "node":
            geom = Point(*tf.transform(el["lon"], el["lat"]))
        elif el["type"] == "way" and "geometry" in el:
            xy = [tf.transform(p["lon"], p["lat"]) for p in el["geometry"]]
            if len(xy) >= 4 and xy[0] == xy[-1]:
                geom = Polygon(xy)
            elif len(xy) >= 2:
                geom = LineString(xy)
        elif el["type"] == "relation" and "members" in el:
            polys = []
            for m in el["members"]:
                if m.get("role") == "outer" and "geometry" in m:
                    xy = [tf.transform(p["lon"], p["lat"]) for p in m["geometry"]]
                    if len(xy) >= 4 and xy[0] == xy[-1]:
                        polys.append(Polygon(xy))
            if polys:
                from shapely.ops import unary_union

                geom = unary_union(polys)
        if geom is not None and not geom.is_empty:
            out.append((tags, geom))
    return out


HIGHWAY_HALF_WIDTH = {"motorway": 8, "trunk": 7, "primary": 6, "secondary": 5, "tertiary": 4.5, "residential": 4,
                      "unclassified": 4, "service": 3, "footway": 1.2, "path": 1.0, "cycleway": 1.2, "steps": 1.2,
                      "pedestrian": 3, "living_street": 3.5, "track": 2}


def build_osm(g: Grid):
    geoms = _osm_geoms()
    layers = {k: [] for k in ("building", "water", "tree", "pitch", "pavement", "barrier", "power", "vertical", "road")}
    obstacles = []
    tf_back = _tf("EPSG:32618", "EPSG:4326")
    for tags, geom in geoms:
        if "building" in tags and geom.geom_type in ("Polygon", "MultiPolygon"):
            layers["building"].append(geom)
        if tags.get("natural") == "water" or "waterway" in tags:
            layers["water"].append(geom.buffer(2.0) if geom.geom_type == "LineString" else geom)
        if tags.get("natural") in ("wood", "tree_row", "scrub") or tags.get("landuse") == "forest":
            layers["tree"].append(geom.buffer(3.0) if geom.geom_type == "LineString" else geom)
        if tags.get("natural") == "tree" and geom.geom_type == "Point":
            layers["tree"].append(geom.buffer(4.0))
        if tags.get("leisure") in ("pitch", "track", "stadium") and geom.geom_type in ("Polygon", "MultiPolygon"):
            layers["pitch"].append(geom)
        if tags.get("amenity") == "parking" and geom.geom_type in ("Polygon", "MultiPolygon"):
            layers["pavement"].append(geom)
        hw = tags.get("highway")
        if hw and geom.geom_type == "LineString":
            layers["road"].append(geom.buffer(HIGHWAY_HALF_WIDTH.get(hw, 3.0)))
        if hw and geom.geom_type in ("Polygon", "MultiPolygon") and tags.get("area") == "yes":
            layers["pavement"].append(geom)
        if "barrier" in tags and geom.geom_type in ("LineString", "Polygon"):
            layers["barrier"].append(geom.boundary.buffer(1.0) if geom.geom_type == "Polygon" else geom.buffer(1.0))
        pw = tags.get("power")
        if pw in ("line", "minor_line", "cable") and geom.geom_type == "LineString":
            layers["power"].append(geom.buffer(30.0 if pw == "line" else 15.0))
        if pw in ("tower", "pole", "portal") or tags.get("man_made") in ("mast", "tower", "flagpole", "antenna", "chimney") \
                or tags.get("highway") == "street_lamp":
            c = geom.centroid
            r = 10.0 if pw == "tower" or tags.get("man_made") in ("mast", "tower") else 4.0
            layers["vertical"].append(c.buffer(r))
            lon, lat = tf_back.transform(c.x, c.y)
            h = tags.get("height")
            try:
                h = float(str(h).split()[0]) if h else None
            except ValueError:
                h = None
            obstacles.append(dict(type="Feature", geometry=dict(type="Point", coordinates=[lon, lat]),
                                  properties=dict(source="OSM", kind=pw or tags.get("man_made") or "street_lamp",
                                                  height_agl_m=h)))
    out = {}
    for k, gs in layers.items():
        if gs:
            a = rasterize([(mapping(x), 1) for x in gs], out_shape=g.shape, transform=g.transform, fill=0,
                          all_touched=True, dtype="uint8")
        else:
            a = np.zeros(g.shape, np.uint8)
        out[k] = a
        write(f"osm_{k}", a, g, dtype="uint8")
    log("osm layers:", {k: len(v) for k, v in layers.items()})
    return out, obstacles


# ------------------------------------------------------------------ FAA DOF + site obstacles
def dof_obstacles():
    feats = []
    p = RAW / "faa_dof.json"
    if p.exists():
        for f in json.loads(p.read_text()).get("features", []):
            a, geo = f.get("attributes", {}), f.get("geometry", {})
            h_ft = a.get("AGL") or a.get("AGL_HT") or a.get("agl")
            feats.append(dict(type="Feature", geometry=dict(type="Point", coordinates=[geo.get("x"), geo.get("y")]),
                              properties=dict(source="FAA DOF", kind=a.get("TYPE_CODE") or a.get("Type_Code"),
                                              oas=a.get("OAS") or a.get("OAS_NUMBER"),
                                              height_agl_m=round(float(h_ft) * 0.3048, 1) if h_ft else None)))
    for o in site().get("obstacles", []):
        feats.append(dict(type="Feature", geometry=dict(type="Point", coordinates=[o["lon"], o["lat"]]),
                          properties=dict(source=o["source"] + " (config)", kind=o["type"], id=o["id"],
                                          height_agl_m=o["height_agl_m"])))
    return feats


# ------------------------------------------------------------------ fusion -> prior class
def build_prior(g: Grid, hag, lcls, osm, ndvi):
    H, W = g.shape
    pc = np.full((H, W), IDX["unknown"], np.uint8)
    conf = np.zeros((H, W), np.float32)
    veg = np.isin(lcls, (3, 4, 5))

    def put(mask, cls, c):
        sel = mask & (pc == IDX["unknown"])
        pc[sel] = IDX[cls]
        conf[sel] = c

    put((lcls == 6) | (osm["building"] > 0), "building", 0.9)
    put((osm["vertical"] > 0) | np.isin(lcls, (14, 15)), "pole_wire", 0.8)
    put((lcls == 9) | (osm["water"] > 0), "water", 0.8)
    put((hag > 2.0) & (veg | (osm["tree"] > 0) | (hag > 4.0)), "tree", 0.8)
    put((hag > 0.3) & (hag <= 2.0) & veg, "tall_veg", 0.5)
    put((hag > 0.5), "rough", 0.4)                       # unclassified above-ground stuff (benches, goals, fences)
    put(((osm["road"] > 0) | (osm["pavement"] > 0)) & (hag < 0.3), "pavement", 0.5)
    green = np.nan_to_num(ndvi, nan=-1) > 0.15
    put((osm["pitch"] > 0) & (hag < 0.3), "short_grass", 0.5)
    put(green & (hag < 0.15), "short_grass", 0.25)
    write("prior_class", pc, g, dtype="uint8", tags=dict(note="rule-based prior; can rule out, never certifies safe"))
    write("prior_conf", conf, g)
    # hazard buffer raster (metres to nearest prior hazard) for the planner
    hz = np.isin(pc, (IDX["building"], IDX["pole_wire"], IDX["water"], IDX["tree"])) | (osm["power"] > 0) | (osm["barrier"] > 0)
    dist = ndimage.distance_transform_edt(~hz) * g.res
    write("hazard_dist", dist.astype(np.float32), g, tags=dict(units="m to nearest prior hazard"))
    write("hazard_buffer", ((osm["power"] > 0) | (osm["vertical"] > 0) | (osm["barrier"] > 0)).astype(np.uint8), g, dtype="uint8")
    log("prior class histogram:", {k: int((pc == i).sum()) for k, i in IDX.items() if (pc == i).any()})
    return pc


def quicklooks():
    from PIL import Image

    ql = OUT / "quicklook"
    ql.mkdir(exist_ok=True)
    from cloudbreak.common.classes import CLASSES, COLORS

    for p in sorted(OUT.glob("*.tif")):
        if p.stem == "ortho_hr":
            continue
        with rasterio.open(p) as src:
            f = max(1, src.width // 1024)
            a = src.read(out_shape=(src.count, src.height // f, src.width // f), resampling=Resampling.nearest)
        if p.stem == "prior_class":
            lut = np.array([COLORS[c] for c in CLASSES], np.uint8)
            img = lut[np.clip(a[0], 0, len(CLASSES) - 1)]
            Image.fromarray(img, "RGBA").save(ql / f"{p.stem}.png")
            continue
        if a.shape[0] >= 3:
            img = a[:3].transpose(1, 2, 0)
        else:
            b = a[0].astype(np.float32)
            fin = np.isfinite(b)
            lo, hi = (np.percentile(b[fin], 2), np.percentile(b[fin], 98)) if fin.any() else (0, 1)
            img = (np.clip((b - lo) / max(hi - lo, 1e-6), 0, 1) * 255).astype(np.uint8)
        Image.fromarray(img.astype(np.uint8)).save(ql / f"{p.stem}.png")


def manifest():
    import hashlib

    m = dict(built=time.strftime("%Y-%m-%dT%H:%M:%S"), grid=site_grid().to_dict(), layers={})
    for p in sorted(OUT.glob("*.tif")):
        with rasterio.open(p) as src:
            m["layers"][p.stem] = dict(file=p.name, crs=str(src.crs), res=src.res[0], shape=[src.height, src.width],
                                       dtype=src.dtypes[0], tags=src.tags(),
                                       sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    fs = RAW / "fetch_status.json"
    if fs.exists():
        m["fetch_status"] = json.loads(fs.read_text())
    (OUT / "manifest.json").write_text(json.dumps(m, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-lidar", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    g = site_grid()
    t0 = time.time()
    if not a.only or "ortho" in a.only:
        build_ortho(g)
    dtm = build_dtm(g)
    if a.skip_lidar:
        hag = np.zeros(g.shape, np.float32)
        lcls = np.zeros(g.shape, np.uint8)
    else:
        hag, lcls = build_lidar(g, dtm)
    osm, osm_obs = build_osm(g)
    ndvi = read("ndvi")
    build_prior(g, hag, lcls, osm, ndvi)
    feats = dof_obstacles() + osm_obs
    (OUT / "obstacles.geojson").write_text(json.dumps(dict(type="FeatureCollection", features=feats), indent=1))
    quicklooks()
    manifest()
    log(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
