# globalbenchmarks: landing-strip benchmarks from open aerial imagery around the world

**Started:** Sat 7 Nov 2026 by Max (with AI). Results: [`RESULTS.md`](RESULTS.md) (generated).

Twenty 600 × 600 m tiles: 5 **urban**, 5 **suburban** (each with full-size football pitches; one centred on the **Affton High School** football field), 5 **rural** and 5 **natural** (three rocky **Utah plateaus**, two **forests with clearings**). They cover 7 countries (US, FR, NL, CH, ES, JP, AU) on 4 continents.

Two extra **campus** benchmarks cover whole universities on 1.5 × 1.5 km tiles: **Cal State Long Beach** and **RPI** (including '86 Field, the team's flight-test site).

Each tile is solved with the planner's own strip search: `strip_search` from `cloudbreak/ground/core/planner/strips.py`, with the Tutor's required strip from `config/aircraft_tutor.toml` (51 × 16 m plus 40 m of overrun, slope ≤ 4°). The output is a review/presentation image per site.

**What it isn't:** flight data, or a substitute for core's evidence grid. Every image names its imagery source, so it can't be mistaken for Pi footage, and nothing here feeds the governor.

## Quick start

```powershell
.venv\Scripts\python -m globalbenchmarks.fetch --sheet          # scrape all 20 sites (cached; ~1 min per site, mostly Overpass)
.venv\Scripts\python -m globalbenchmarks.solve                  # solve all -> benchmark.jpg per site, sheets, RESULTS.md (~1 s per site)
.venv\Scripts\python -m globalbenchmarks.solve --only affton    # one site (id or substring); --category natural; --strip 60 20
.venv\Scripts\python -m globalbenchmarks.solve --decider jev    # JEV-9B must make the decisions (fails if it can't load)
.venv\Scripts\python -m pytest globalbenchmarks/tests           # offline tests (synthetic images, no network)
```

**JEV9 Decision vs Planner Decision.**
- The default `--decider auto` uses JEV-9B if it loads. That needs the weights in `C:\cb-data\models\JEV-9B`, a CUDA GPU and the `[jev]` extra; see `cloudbreak/ground/agent/jev.py`. Without them, the planner decides.
- The left panel's title always names the decider that actually ran. On a laptop without JEV it says **Planner Decision**; copy `images/` from a JEV run for slides that say **JEV9 Decision**.
- JEV gets one `choice` question: the strips with full overrun, plus the manual-landing option. The question uses only facts the benchmark measured: surface, axis, open length, max slope and whether the strip is on a mapped pitch. There's no wind and no camera-evidence count, so `jev.decide`'s template isn't used, rather than feeding it invented numbers.
- A strip is accepted like `jev.decide` accepts one: it must beat the manual option and have P ≥ 0.4. Otherwise the decision is a manual landing, and no strip is drawn thick.
- The planner's own decision is its top-ranked strip with full overrun.

## What's in `images/`

| Path | What |
|---|---|
| `images/<category>/<id>/imagery.jpg` | 0.5 m/px, north-up, centred on the site: the clean source image. 1200 × 1200 px (600 m); campus tiles 3000 × 3000 px (1.5 km) |
| `…/benchmark.jpg` | **The review image.** Left: **JEV9 Decision** (or **Planner Decision** where JEV-9B can't run). Right: **Recognition Result** (land classes, steep ground, landable outline). Key below |
| `…/result.json` | Every strip: centre lat/lon, axis, open length, surface, max slope, overlap with OSM hazards / pitches; class histograms; both runs |
| `…/classes.png` | Fused class map (ids from `cloudbreak/common/classes.py`), 0.5 m/px |
| `…/dem.png` | 1 m terrain, 16-bit: `elevation_m = offset_m + value × scale_m` (`meta.json` → `terrain`) |
| `…/osm.json.gz` | OpenStreetMap features in the box: the exact Overpass query core's priors use (`priors/fetch.py: OVERPASS_Q`) |
| `…/meta.json` | Georeference (lat/lon and EPSG:3857 box), source, licence, attribution, zoom / native resolution, fetch time |
| `images/_sheets/benchmark_<category>.jpg`, `benchmark_all.jpg` | Contact sheets of the answers, for slides |
| `images/_sheets/imagery_<category>.jpg` | Contact sheets of the raw imagery |
| `images/results.json` | All results in one file |

Raw tiles are cached in `C:\cb-data\globalbenchmarks\tiles` (not in git), so reruns are offline.

## Sources and licences

All imagery is **aerial orthophotography from national mapping agencies**. At 0.1–0.6 m it's sharper than any free satellite source (Sentinel-2's 10 m would make the 51 × 16 m strip 5 × 2 pixels). Every source can be stored and republished with attribution, or is public domain, so the images can sit in a public repo and go on slides. Esri, Google and Bing basemaps are deliberately not used: their terms don't allow storing tiles.

| Key | Source | Region | Licence | Attribution (burned into every benchmark image) |
|---|---|---|---|---|
| `naip` | USGS NAIP Plus (ImageServer export) | US | Public domain | USGS / USDA, The National Map |
| `gsi` | GSI seamless photo tiles | JP | GSI terms (CC BY 4.0 compatible) | Geospatial Information Authority of Japan |
| `ign` | IGN BD ORTHO (Géoplateforme WMTS) | FR | Licence Ouverte / Etalab 2.0 | IGN France |
| `pdok` | PDOK Luchtfoto RGB | NL | CC BY 4.0 | Beeldmateriaal Nederland / PDOK |
| `swisstopo` | SWISSIMAGE | CH | swisstopo open data | Federal Office of Topography swisstopo |
| `nsw` | NSW Imagery | AU | CC BY 4.0 | Spatial Services NSW |
| `pnoa` | PNOA | ES | CC BY 4.0 | Instituto Geográfico Nacional de España |
| `3dep` | USGS 3DEP elevation (bare earth, best available 1–10 m) | US | Public domain | USGS 3D Elevation Program |
| `terrarium` | Terrain Tiles on AWS (SRTM, EU-DEM, national DEMs) | elsewhere | Open data | Mapzen / AWS Open Data |
| OSM | Overpass API | all | ODbL | OpenStreetMap contributors |

Imagery dates vary by source (e.g. Paris is the summer-2024 IGN flight and still shows the temporary Olympic venues).

## Sites

Site list and the question each one asks: [`sites.py`](sites.py). Suburban pitches were located from OSM (`leisure=pitch`, `sport=soccer|american_football`). Affton is centred on OSM way 633082326, the Affton High School American football field.

| Category | Sites |
|---|---|
| Urban | Nishi-Shinjuku Tokyo (JP) · Champ de Mars Paris (FR) · Amsterdam Centrum (NL) · Sydney CBD and Hyde Park (AU) · Gran Vía Madrid (ES) |
| Suburban | **Affton High School, MO (US)** · Almere sports park (NL) · Tama New Town (JP) · Castle Hill, Sydney (AU) · Montigny-le-Bretonneux (FR) |
| Rural | Story County, Iowa (US) · Beauce (FR) · Flevoland polder (NL) · Tokachi plain, Hokkaido (JP) · Riverina, NSW (AU) |
| Natural | **Island in the Sky, UT** · **Cedar Mesa, UT** · **Hatch Point mesa, UT** (US) · Franches-Montagnes wooded pasture (CH) · Landes pine forest with clear-cut parcels (FR) |
| Campus (extra, 1.5 km) | **Cal State Long Beach** (whole campus, OSM way 207858609) · **RPI, Troy NY** ('86 Field to East Campus) |

Two first picks were replaced after review:
- **The Wedge, San Rafael Swell:** the tile landed in the bottom of the Little Grand Canyon, not on a plateau.
- **Capitol State Forest, WA:** unbroken conifer on steep ground, with no clearing in the tile.

## How the solver works (`solve.py`)

Two runs per site, both through the planner's `strip_search` on a 1 m local grid (15° heading steps). A grid cell counts only if all four 0.5 m pixels in it are landable.

| Run | Inputs | Meaning |
|---|---|---|
| **camera** | Image classes + terrain slope | What a straight-down camera alone supports (the Pi on the Tutor, no map) |
| **fused** | Camera + OSM priors, mapped like core's `build_prior` | The answer a planner would act on: **both panels** of `benchmark.jpg` |

1. **Camera classes** (`camera_labels`, ontology from `cloudbreak/common/classes.py`). Colour and texture rules:
   - excess-green vegetation;
   - **tree** = vegetation with crown texture (measured after a ~2.5 m median, which erases painted pitch lines but not crowns) or with dark gaps between crowns (shadow fraction in a ~7.5 m window);
   - grey + smooth → **pavement**; other smooth → **dirt**; textured non-green → **rough**; bluish dark smooth → **water**;
   - shadow and blown-out highlights → **unknown** (never landable).

   Thresholds come from sampled patches:

   | Patch | Texture after median (p50) | Shadow fraction (p90) |
   |---|---|---|
   | Affton turf (with yard lines) | 5.5 | 0.00 |
   | Lawns / pasture | 1.8–2.6 | 0.00–0.09 |
   | Deciduous trees | 8.4–11.4 | 0.46–0.75 |
   | Spruce | 16.5 | 0.99 |
2. **Terrain slope.** Same recipe as core's `build_dtm` (Gaussian, then gradient), but smoothed to the source's real resolution: 2 m for 3DEP, 12 m for the ~30 m global tiles, whose upsampled steps would otherwise read as slopes. Steeper than `slope_max_deg` (4°) → not landable (red hatch).
3. **OSM fusion** (`osm_layers` + `fuse`). These mirror core's `build_osm` / `build_prior`:
   - Buildings, masts / poles / street lamps, water, woods, power-line corridors (30 / 15 m) and barriers are hazards.
   - Roads and parking become pavement, but only where the image doesn't show a hazard.
   - **Pitches:** painted lines, numbers and logos read as texture, so inside an OSM pitch / track the camera's texture classes become short grass unless the image shows shadow. Core uses LiDAR (`hag < 0.3`) for this; shadow is the single-image stand-in.
4. **Landable** = safe class (`short_grass`, `pavement`, `dirt`) AND slope ≤ 4° AND at least `hazard_buffer_m` from any hazard. That's core's `plan()` mask, without the evidence-grid terms.
5. **Ranking** (like the planner: feasible first). Strips with ≥ 91 m open length along the axis (strip + `overrun_margin_m`) come first. Then surface preference (`SURFACE_PREF`: grass 1.0, pavement 0.7, dirt 0.5, reduced by slope).
6. **Thinning:** at most **one strip per mapped pitch**. Strip centres are at least 0.75 L apart; on a 600 m tile that allows up to 5 strips.
   - Bigger tiles scale with k = tile / 600 m: candidates per heading 3k², spacing 0.75 L·k, up to 5k² strips.
   - Without that scaling, the flattest fields took every candidate slot on a campus, and '86 Field was never looked at.

**OSM as weak ground truth for the camera run.** A camera strip overlapping an OSM building / water / wood / power / barrier feature (> 2 % of its area) is a **conflict**, i.e. a likely false positive (counted in `RESULTS.md`). A strip with ≥ 50 % of its area on an OSM pitch is a **pitch hit**.

## Reading a benchmark image

Every image (and every contact-sheet tile) carries the same text and nothing else:

1. **Location:** place and country.
2. **Strips found**, and how many of them have **full overrun** (in green, the same green as those strips).
3. **Source:** imagery (with licence), terrain and OpenStreetMap. The licences require this attribution; contact-sheet tiles use a short form.
4. **Panel titles:** **JEV9 Decision** (or **Planner Decision**) on the left, **Recognition Result** on the right. Contact-sheet tiles show the left panel only.

Both panels use the same run (camera + OSM + terrain). The rest is graphics; this is the key:

| Panel | Mark | Meaning |
|---|---|---|
| JEV9 / Planner Decision | **Green** rectangle | Strip with full overrun (≥ 91 m open along its axis) |
| | **Orange** rectangle | Strip fits, but less than 91 m of open ground along its axis |
| | Thick outline | The strip the decider picked. No thick strip means it chose a manual landing |
| | Arrow inside a strip | Strip axis (either landing direction) |
| | Scale bar, N arrow | 100 m; all tiles are north-up, 600 × 600 m |
| Recognition Result | Class tint | Colours from `cloudbreak/common/classes.py` `COLORS`: grass green, pavement grey, dirt tan, tree dark green, building red, water blue, rough purple, wires / masts / barriers bright red |
| | **Red hatch** | Slope > 4° |
| | **Cyan outline** | Landable ground |

The camera-only run isn't drawn; its strips and their OSM conflicts are in `result.json` and `RESULTS.md`, together with per-strip details (surface, open length, slope, OSM overlap, pitch hits) and the JEV probabilities when JEV decided.

## Findings

Per-site numbers: [`RESULTS.md`](RESULTS.md). Run of Sat 7 Nov ~22:50, planner decisions (JEV-9B not available on this laptop). Reviewed by eye; there is no hand-labelled ground truth yet.

| Category | What happened | Verdict |
|---|---|---|
| Urban | Tokyo, Amsterdam, Sydney and Madrid: no strip, manual landing. **Paris:** the pick is a "pavement" strip on the white roof of the temporary 2024 Olympic arena at the southeast end of the Champ de Mars (48.8536, 2.3019). The arena is gone from current OSM, and one image has no height | 4 of 5 correct. **Paris is a false positive** (stale map + no height): keep it as a regression case |
| Suburban | Every site puts strips on OSM pitches (1–3 per site). **Affton:** a strip on the High School football field (172 m open), but the planner picks a strip on the north practice field. Both clear the overrun, and the planner's score has no pitch preference. Camera-only misses the turf field: painted numbers, logo and lettering read as tree / rough on ~28 % of it. **Almere:** all 5 camera-only strips sit on OSM hazards (fences between pitches, floodlight masts, tree rows that are leafless in the spring flight); the fused strips avoid them | Pitches work once OSM says "pitch". Map priors are essential in suburbia |
| Rural | 4–5 strips everywhere, 35–98 % landable | Geometrically right, but **green crops read as short grass** (e.g. Iowa corn / soy). A single RGB image can't tell crop height; core uses LiDAR for that |
| Natural (Utah) | **Island in the Sky:** terrain tilts 5–7°, so slope rules out nearly everything. **Cedar Mesa:** continuous pinyon-juniper, nothing open. **Hatch Point:** flat open mesa, but junipers every 20–30 m leave only two short strips (no full overrun), so manual landing | Correct calls; slope and scattered trees behave as intended |
| Natural (forest) | **Jura:** 2 strips with full overrun in the flatter pasture; one camera-only strip sits under a power line that only OSM knows. **Landes:** two short strips on a parcel of young pine rows that the camera reads as grass; no full overrun, so manual landing | Jura correct. **Landes shows young plantation ≈ grass**, the same failure as crops |
| Campus (1.5 km) | **RPI:** 12 strips, one per field: Harkness, Stadium, Rugby, Renwyck, Robison, the East Campus baseball / softball fields, **Anderson Field** and **'86 Field** (128 m open, full overrun). The planner picks Harkness Field. Nothing on the academic core or the hillside down to Troy, which is hatched as too steep. **CSULB:** 10 strips across the northeast athletics complex (baseball outfield, track infield, soccer, George Allen Field) and the open ground in the northwest corner. Nothing on the Walter Pyramid, the parking structures or the academic blocks. CSULB slope is from terrain tiles: the 3DEP server returned 502 during the fetch | Correct calls on both. Before thinning scaled with tile size, '86 Field was missed: the flattest fields took every candidate slot |

**Takeaways for the presentation:**
1. Strip search plus map priors finds the obvious fields (football and soccer pitches, pasture) and says "no" in cities and on rough plateaus.
2. A camera-only system is fooled by things it can't see: wires, fences, masts, leafless trees, and painted lines that look like texture.
3. The remaining errors all need **height**: roofs, crops, young trees. That's the case for LiDAR / structure-from-motion in core.

## Known limitations

- **No height from one image.** A smooth flat roof reads as pavement, and a green crop as short grass; core has LiDAR for both. Fused mode relies on OSM buildings, which miss temporary structures and unmapped areas.
- **Global terrain is coarse.** Outside the US, the ~30 m terrain tiles are surface models (SRTM sees buildings), so slope in dense cities is approximate; urban tiles mostly fail on buildings anyway. 3DEP in the US is bare earth at 1–10 m.
- **Things too small to see at 0.5 m:** goalposts, fences without OSM, wires without OSM, rocks under 1 m, stumps in clear-cuts. The strip size includes dispersion but not unseen obstacles.
- **Colour rules are tuned on a handful of patches** (table above). Seasons and sun angle differ between sources.
- **Qualitative:** there's no hand-labelled ground truth yet; OSM is the reference.
- **Not flight-qualified:** benchmark imagery, never flight data.

## Kept separate from the flight software

Same rules as `videolab/`:
- Everything lives in `globalbenchmarks/`.
- Dependencies run one way: it **reads** `strip_search`, `required_dims`, `load_aircraft`, `Grid`, `offset_latlon`, the class list and core's Overpass query. Nothing in `cloudbreak/` imports it.
- Its tests run separately (`python -m pytest globalbenchmarks/tests`); the flight suite only collects `tests/`.
- No new dependencies.
