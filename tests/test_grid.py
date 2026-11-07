import time
import numpy as np
from cloudbreak.common.classes import IDX, K
from cloudbreak.common.geodesy import Grid
from cloudbreak.ground.core.mapping.grid import EvidenceGrid


def _probs(n, cls, p=0.9):
    a = np.full((n, K), (1 - p) / (K - 1), np.float32)
    a[:, cls] = p
    return a


def test_vacuous_cell_is_unsafe_and_prior_cannot_make_safe():
    ev = EvidenceGrid(Grid(0, 100, 0.5, 20, 20))
    pc = np.full((20, 20), IDX["short_grass"], np.uint8)
    ev.add_prior(pc, np.ones((20, 20), np.float32))
    assert ev.p_safe_lb().max() == 0.0


def test_repeated_good_views_make_safe():
    ev = EvidenceGrid(Grid(0, 100, 0.5, 4, 4))
    r, c = np.zeros(50, int), np.zeros(50, int)
    for _ in range(6):
        ev.observe(r, c, _probs(50, IDX["short_grass"], 0.95), np.full(50, 0.9))
    assert ev.p_safe_lb()[0, 0] >= 0.75 and ev.views[0, 0] == 6


def test_one_person_sighting_blocks_but_salt_noise_does_not():
    ev = EvidenceGrid(Grid(0, 100, 0.5, 4, 4))
    r, c = np.zeros(100, int), np.zeros(100, int)
    for _ in range(6):
        ev.observe(r, c, _probs(100, IDX["short_grass"], 0.95), np.full(100, 0.9))
    noisy = _probs(100, IDX["short_grass"], 0.95)
    noisy[:2] = _probs(2, IDX["person"], 0.9)                 # 2 stray pixels
    ev.observe(r, c, noisy, np.full(100, 0.9))
    assert ev.p_safe_lb()[0, 0] > 0.0                          # not blocked by salt noise
    ev.observe(r, c, _probs(100, IDX["person"], 0.9), np.full(100, 0.9))   # real person blob
    assert ev.p_safe_lb()[0, 0] == 0.0
