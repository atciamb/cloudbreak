"""Cloudbreak landability ontology (shared by priors, perception, grid, planner, UI)."""
from __future__ import annotations

CLASSES = [
    "unknown",      # 0  no/insufficient evidence -- never safe
    "short_grass",  # 1  mown grass / turf -- landable
    "pavement",     # 2  asphalt/concrete -- landable (harder on a foam airframe)
    "dirt",         # 3  bare soil/gravel -- landable if smooth
    "tall_veg",     # 4  crops, brush, long grass -- not landable
    "tree",         # 5
    "water",        # 6
    "building",     # 7
    "vehicle",      # 8  dynamic hazard
    "person",       # 9  dynamic hazard
    "pole_wire",    # 10 thin vertical/overhead obstacles
    "rough",        # 11 rocks, debris, steps, ruts
]
IDX = {c: i for i, c in enumerate(CLASSES)}
K = len(CLASSES)

SAFE = ("short_grass", "pavement", "dirt")
SAFE_IDX = tuple(IDX[c] for c in SAFE)
HAZARD = ("tall_veg", "tree", "water", "building", "vehicle", "person", "pole_wire", "rough")
HAZARD_IDX = tuple(IDX[c] for c in HAZARD)
DYNAMIC = ("vehicle", "person")
DYNAMIC_IDX = tuple(IDX[c] for c in DYNAMIC)

# surface preference for ranking (foam trainer: turf/grass best, pavement OK, dirt worst)
SURFACE_PREF = {"short_grass": 1.0, "pavement": 0.7, "dirt": 0.5}

# RGBA colours for UI overlays
COLORS = {
    "unknown": (0, 0, 0, 0), "short_grass": (80, 200, 90, 160), "pavement": (150, 150, 150, 160),
    "dirt": (180, 140, 90, 160), "tall_veg": (200, 200, 40, 170), "tree": (20, 110, 40, 190),
    "water": (40, 110, 230, 190), "building": (200, 60, 60, 200), "vehicle": (255, 120, 0, 220),
    "person": (255, 0, 200, 230), "pole_wire": (255, 0, 0, 230), "rough": (120, 60, 160, 180),
}
