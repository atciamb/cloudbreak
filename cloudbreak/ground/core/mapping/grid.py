"""Bayesian evidence grid (Dirichlet per cell) -- "unknown is never safe" made precise.

Each cell holds Dirichlet concentration alpha over the K Cloudbreak classes, starting near-vacuous
(alpha0 per class). A camera observation of the cell adds w * p (p = calibrated class probabilities,
w = view quality weight). Consequences:
  * vacuity u = K / sum(alpha) is high until real evidence arrives -> unobserved cells are never safe
  * P(safe) uses the *lower* 5 % credible bound of Beta(alpha_safe, alpha_rest) (marginal of the Dirichlet)
  * priors may only add evidence to HAZARD classes (rule-out); they never add safe evidence
  * a cell needs >= min_views distinct good views before it can be safe
  * dynamic hazards (person/vehicle): any single credible sighting blocks the cell for block_s seconds
    (noisy-OR style), and their evidence decays with time constant tau_s so they can clear when gone
"""
from __future__ import annotations

import time

import numpy as np
from scipy import ndimage
from scipy.special import betaincinv

from cloudbreak.common.classes import DYNAMIC_IDX, HAZARD_IDX, IDX, K, SAFE_IDX
from cloudbreak.common.geodesy import Grid


class EvidenceGrid:
    def __init__(self, grid: Grid, alpha0: float = 0.05, min_views: int = 3, tau_s: float = 90.0,
                 block_s: float = 120.0, kappa: float = 4.0):
        self.grid = grid
        self.kappa = kappa          # effective independent pseudo-observations per good view of a cell
        H, W = grid.shape
        self.alpha = np.full((H, W, K), alpha0, np.float32)
        self.alpha0 = alpha0
        self.views = np.zeros((H, W), np.uint16)
        self.last_obs = np.zeros((H, W), np.float64)
        self.dyn_block_until = np.zeros((H, W), np.float64)
        self.min_views, self.tau_s, self.block_s = min_views, tau_s, block_s
        self._t_decay = time.time()
        self.version = 0
        self.n_frames = 0

    # ---------------------------------------------------------------- priors (rule-out only)
    def add_prior(self, prior_class: np.ndarray, prior_conf: np.ndarray, strength: float = 3.0):
        for c in HAZARD_IDX:
            m = prior_class == c
            self.alpha[..., c][m] += strength * prior_conf[m]
        self.version += 1

    # ---------------------------------------------------------------- observations
    def _decay(self, t: float):
        dt = t - self._t_decay
        if dt > 0:
            f = np.float32(np.exp(-dt / self.tau_s))
            for c in DYNAMIC_IDX:
                a = self.alpha[..., c]
                a[:] = self.alpha0 + (a - self.alpha0) * f
            self._t_decay = t

    def observe(self, r: np.ndarray, c: np.ndarray, probs: np.ndarray, w: np.ndarray, t: float | None = None):
        """r, c: int cell indices (N,); probs: (N, K) calibrated; w: (N,) weights in [0, 1]."""
        t = time.time() if t is None else t
        self._decay(t)
        H, W = self.grid.shape
        ok = (r >= 0) & (r < H) & (c >= 0) & (c < W) & (w > 0)
        r, c, probs, w = r[ok], c[ok], probs[ok], w[ok]
        if r.size == 0:
            return 0
        lin = r * W + c
        flat = self.alpha.reshape(-1, K)
        # Pixels of one frame that fall in the same cell are strongly correlated: aggregate them into ONE
        # observation per cell per frame worth kappa * mean_weight pseudo-counts, split by mean probabilities.
        cnt = np.bincount(lin, minlength=H * W)
        sw = np.bincount(lin, weights=w, minlength=H * W)
        has = np.nonzero(cnt)[0]
        wmean = sw[has] / cnt[has]
        dyn_cell = np.zeros(len(has), bool)
        for k in range(K):
            sk = np.bincount(lin, weights=w * probs[:, k], minlength=H * W)[has]
            pk = sk / np.maximum(sw[has], 1e-9)
            flat[has, k] += (self.kappa * wmean * pk).astype(np.float32)
            if k in DYNAMIC_IDX:
                dyn_cell |= (pk > 0.5) & (wmean > 0.4)      # coherent detection in this cell, not one stray pixel
        wsum = np.zeros(H * W)
        wsum[has] = wmean
        wsum = wsum.reshape(H, W)
        seen = wsum > 0.3
        self.views[seen] += 1
        self.last_obs[seen] = t
        # one credible dynamic-hazard sighting blocks the cell (noisy-OR). "Credible" = the cell's aggregated
        # person/vehicle probability in this frame > 0.5 -- robust to salt-noise pixels, immediate for a real blob.
        if dyn_cell.any():
            rr, cc = np.divmod(has[dyn_cell], W)
            self.dyn_block_until[rr, cc] = t + self.block_s
        self.version += 1
        self.n_frames += 1
        return int(seen.sum())

    # ---------------------------------------------------------------- derived maps
    @property
    def S(self):
        return self.alpha.sum(-1)

    def vacuity(self):
        """1.0 = no evidence beyond the vacuous prior; -> 0 as evidence accumulates (subjective-logic u)."""
        return (K * self.alpha0) / np.maximum(self.S, 1e-6)

    def p_safe_mean(self):
        return self.alpha[..., list(SAFE_IDX)].sum(-1) / self.S

    def p_safe_lb(self, q: float = 0.05):
        a = self.alpha[..., list(SAFE_IDX)].sum(-1).astype(np.float64)
        b = self.S.astype(np.float64) - a
        lb = betaincinv(np.maximum(a, 1e-6), np.maximum(b, 1e-6), q)
        lb[self.views < self.min_views] = 0.0
        lb[self.dyn_block_until > time.time()] = 0.0
        return lb.astype(np.float32)

    def evidence_mass(self):
        return self.S - K * self.alpha0

    def class_map(self, min_mass: float = 1.0):
        cm = self.alpha.argmax(-1).astype(np.uint8)
        cm[self.evidence_mass() < min_mass] = IDX["unknown"]
        return cm

    def hazard_mask(self, p_thr: float = 0.35, buffer_m: float = 0.0):
        haz = self.alpha[..., list(HAZARD_IDX)].sum(-1) / self.S
        m = (haz > p_thr) & (self.evidence_mass() > 0.5)
        m |= self.dyn_block_until > time.time()
        if buffer_m > 0:
            m = ndimage.binary_dilation(m, iterations=max(1, int(round(buffer_m / self.grid.res))))
        return m

    def save(self, path):
        np.savez_compressed(path, alpha=self.alpha, views=self.views, last_obs=self.last_obs,
                            dyn_block_until=self.dyn_block_until, version=self.version, n_frames=self.n_frames,
                            grid=np.array([self.grid.x0, self.grid.y0, self.grid.res, self.grid.width, self.grid.height]))

    def load(self, path):
        d = np.load(path)
        g = d["grid"]
        if not (abs(g[0] - self.grid.x0) < 1e-6 and abs(g[1] - self.grid.y0) < 1e-6 and int(g[3]) == self.grid.width):
            raise ValueError("saved grid does not match the working grid")
        self.alpha[:] = d["alpha"]
        self.views[:] = d["views"]
        self.last_obs[:] = d["last_obs"]
        self.dyn_block_until[:] = d["dyn_block_until"]
        self.version = int(d["version"]) + 1
        self.n_frames = int(d["n_frames"])

    def summary(self):
        return dict(version=self.version, frames=self.n_frames, observed_cells=int((self.views > 0).sum()),
                    safe_cells=int((self.p_safe_lb() > 0.8).sum()))
