"""Benchmark sites (5 per category) and the openly licensed imagery / terrain sources they come from.

Every source here is free to download, store and republish with attribution (or public domain), so the
compiled images can live in the repo and go on slides. Esri / Google / Bing basemaps are deliberately NOT used:
their terms don't allow storing tiles.

Imagery is aerial orthophotography from national mapping agencies (0.1-0.6 m native), which is sharper than
any free satellite source; everything is resampled to the same ground resolution (GSD_M).
"""
from __future__ import annotations

from dataclasses import dataclass

EXTENT_M = 600.0        # square benchmark tile side (ground metres); campus tiles are larger (Site.extent_m)
GSD_M = 0.5             # metres per pixel of the compiled imagery (1200 x 1200 px for a 600 m tile)
CATEGORIES = ("urban", "suburban", "rural", "natural", "campus")


@dataclass(frozen=True)
class Source:
    name: str
    kind: str            # "xyz" (Web Mercator tiles) or "export" (ArcGIS ImageServer exportImage, any bbox)
    url: str
    max_zoom: int
    licence: str
    attribution: str
    region: str


SOURCES = {
    "naip": Source("USGS NAIP Plus", "export",
                   "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer/exportImage", 0,
                   "Public domain (US Government)", "USGS / USDA, The National Map: NAIP Plus orthoimagery", "US"),
    "gsi": Source("GSI seamless photo", "xyz", "https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg", 18,
                  "GSI Terms of Use (CC BY 4.0 compatible)", "Geospatial Information Authority of Japan (GSI tiles)", "JP"),
    "ign": Source("IGN BD ORTHO", "xyz",
                  "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=ORTHOIMAGERY.ORTHOPHOTOS"
                  "&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/jpeg", 19,
                  "Licence Ouverte / Etalab 2.0", "IGN France, BD ORTHO", "FR"),
    "pdok": Source("PDOK Luchtfoto RGB", "xyz",
                   "https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0/Actueel_orthoHR/EPSG:3857/{z}/{x}/{y}.jpeg", 19,
                   "CC BY 4.0", "Beeldmateriaal Nederland / PDOK", "NL"),
    "swisstopo": Source("swisstopo SWISSIMAGE", "xyz",
                        "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/{z}/{x}/{y}.jpeg", 19,
                        "swisstopo open data (free use with attribution)", "Federal Office of Topography swisstopo", "CH"),
    "nsw": Source("NSW Spatial Services imagery", "xyz",
                  "https://maps.six.nsw.gov.au/arcgis/rest/services/public/NSW_Imagery/MapServer/tile/{z}/{y}/{x}", 19,
                  "CC BY 4.0", "Spatial Services, NSW Department of Customer Service", "AU"),
    "pnoa": Source("IGN Spain PNOA", "xyz",
                   "https://www.ign.es/wmts/pnoa-ma?request=GetTile&service=WMTS&VERSION=1.0.0&Layer=OI.OrthoimageCoverage"
                   "&Style=default&Format=image/jpeg&TileMatrixSet=GoogleMapsCompatible&TileMatrix={z}&TileRow={y}&TileCol={x}", 19,
                   "CC BY 4.0", "PNOA cedido por Instituto Geografico Nacional de Espana", "ES"),
}

TERRAIN = {
    "3dep": Source("USGS 3DEP", "export",
                   "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage", 0,
                   "Public domain (US Government)", "USGS 3D Elevation Program (bare earth, best available 1-10 m)", "US"),
    "terrarium": Source("AWS Terrain Tiles", "xyz", "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png", 15,
                        "Open data (per-source attribution)",
                        "Terrain Tiles on AWS (Mapzen): SRTM, EU-DEM, GMTED and national DEMs, ~10-30 m", "global"),
}

OSM_ATTRIBUTION = "OpenStreetMap contributors (ODbL)"


@dataclass(frozen=True)
class Site:
    id: str
    category: str
    name: str
    country: str
    lat: float
    lon: float
    source: str
    expect: str          # what a reviewer should look for; the benchmark question this site asks
    focus: str = ""      # optional feature the tile is centred on
    extent_m: float = EXTENT_M   # square tile side; campuses use a bigger tile to show the whole campus

    @property
    def terrain(self) -> str:
        return "3dep" if self.source == "naip" else "terrarium"


SITES: list[Site] = [
    # --- urban: dense blocks, plazas and city parks. Mostly a "find nothing / don't land on a roof" test.
    Site("urban_tokyo_shinjuku", "urban", "Nishi-Shinjuku, Tokyo", "JP", 35.6905, 139.6925, "gsi",
         "high-rises, plazas and Shinjuku Central Park; flat roofs and plazas must not become strips"),
    Site("urban_paris_champ_de_mars", "urban", "Champ de Mars, Paris", "FR", 48.8556, 2.2986, "ign",
         "long lawns between tree rows and buildings: tempting, but tree-lined and crowded"),
    Site("urban_amsterdam_centrum", "urban", "Amsterdam Centrum", "NL", 52.3727, 4.8930, "pdok",
         "canal ring: water, narrow streets and pitched roofs; nothing should qualify"),
    Site("urban_sydney_cbd", "urban", "Sydney CBD and Hyde Park", "AU", -33.8720, 151.2100, "nsw",
         "towers plus Hyde Park lawns under trees; strips only where lawn is open"),
    Site("urban_madrid_centro", "urban", "Gran Via, Madrid", "ES", 40.4200, -3.7050, "pnoa",
         "compact old town, flat terraces; nothing should qualify"),
    # --- suburban: houses and streets with full-size football pitches (the realistic emergency field).
    Site("suburban_affton_mo", "suburban", "Affton High School, Affton MO", "US", 38.55885, -90.32620, "naip",
         "the American football field (OSM way 633082326) should hold a strip along its long axis",
         focus="Affton High School football field"),
    Site("suburban_almere", "suburban", "Almere Stad sports park", "NL", 52.3905, 5.2580, "pdok",
         "a block of full-size soccer pitches next to housing"),
    Site("suburban_tama_new_town", "suburban", "Tama New Town, Tokyo", "JP", 35.6154, 139.4243, "gsi",
         "soccer ground among apartment blocks; Japanese school grounds are often bare dirt"),
    Site("suburban_castle_hill", "suburban", "Castle Hill, Sydney", "AU", -33.7274, 150.9988, "nsw",
         "suburban oval / soccer field surrounded by houses and trees"),
    Site("suburban_montigny", "suburban", "Montigny-le-Bretonneux", "FR", 48.7753, 2.0248, "ign",
         "stade with soccer pitches next to a new-town suburb"),
    # --- rural: open farmland. Many geometric fits; crops vs. short grass is the hard part.
    Site("rural_iowa_story_county", "rural", "Story County, Iowa", "US", 42.1000, -93.4500, "naip",
         "corn/soy sections and gravel roads: lots of fits, but tall crops are not landable"),
    Site("rural_beauce", "rural", "Beauce plain near Voves", "FR", 48.2500, 1.7000, "ign",
         "huge flat cereal fields with tramlines"),
    Site("rural_flevoland", "rural", "Flevoland polder near Dronten", "NL", 52.5500, 5.6200, "pdok",
         "rectangular polder plots split by drainage ditches (water hazards)"),
    Site("rural_tokachi", "rural", "Tokachi plain, Hokkaido", "JP", 42.9200, 143.1000, "gsi",
         "patchwork fields with windbreak tree rows"),
    Site("rural_riverina", "rural", "Riverina near Temora, NSW", "AU", -34.5000, 147.4000, "nsw",
         "broadacre wheat/sheep country, few obstacles"),
    # --- natural: rocky Utah plateaus (slope, ledges, slickrock) and forests with clearings.
    Site("natural_utah_island_in_the_sky", "natural", "Island in the Sky mesa, Canyonlands UT", "US", 38.3950, -109.8650,
         "naip", "slickrock and scrub on a mesa top; the rim and ledges must be excluded by slope"),
    Site("natural_utah_cedar_mesa", "natural", "Cedar Mesa, UT", "US", 37.4700, -109.9200, "naip",
         "pinyon-juniper plateau cut by canyons; open patches are small and rocky"),
    Site("natural_utah_hatch_point", "natural", "Hatch Point mesa, UT", "US", 38.3814, -109.6370, "naip",
         "rocky juniper scrub giving way to open flat mesa top: strips belong on the flat, not in the rock"),
    Site("natural_jura_franches_montagnes", "natural", "Franches-Montagnes wooded pasture, Jura", "CH", 47.2250, 7.0400,
         "swisstopo", "wooded pasture: grass clearings between spruce stands"),
    Site("natural_landes_forest", "natural", "Landes pine forest, Gascony", "FR", 44.2000, -0.8061, "ign",
         "flat pine plantation with clear-cut parcels: stumps and slash look open but are rough"),
    # --- campus (extra benchmarks, 1.5 km tiles): whole university campuses with their athletic fields.
    Site("campus_csulb", "campus", "Cal State Long Beach campus", "US", 33.7818, -118.1156, "naip",
         "Jack Rose Track, George Allen Field and the NE athletics fields should hold strips; the Walter Pyramid, "
         "parking structures and dense academic blocks should not", focus="whole campus (OSM way 207858609)",
         extent_m=1500.0),
    Site("campus_rpi", "campus", "RPI campus, Troy NY", "US", 42.7318, -73.6734, "naip",
         "'86 Field (the team's flight-test site) and the East Campus fields (Harkness, Stadium, Rugby, Renwyck) should "
         "hold strips; the hillside down to Troy and the academic core should not", focus="'86 Field to East Campus",
         extent_m=1500.0),
]

SITE_BY_ID = {s.id: s for s in SITES}


def select(only: str | None = None, category: str | None = None) -> list[Site]:
    out = SITES
    if category:
        out = [s for s in out if s.category in category.split(",")]
    if only:
        keys = only.split(",")
        out = [s for s in out if any(k == s.id or k in s.id for k in keys)]
    return out
