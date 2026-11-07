"""Configuration loading and well-known paths.

Code lives in the repo; everything heavy (priors, weights, keys, sessions) lives under
CLOUDBREAK_DATA (default C:\\cb-data) so nothing large ever lands in git.
"""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


def data_dir() -> Path:
    default = r"C:\cb-data" if os.name == "nt" else str(Path.home() / "cb-data")
    p = Path(os.environ.get("CLOUDBREAK_DATA", default))
    p.mkdir(parents=True, exist_ok=True)
    return p


def priors_dir(kind: str = "") -> Path:
    p = data_dir() / "priors" / kind if kind else data_dir() / "priors"
    p.mkdir(parents=True, exist_ok=True)
    return p


@lru_cache(maxsize=None)
def load_toml(name: str) -> dict:
    path = CONFIG_DIR / name
    with open(path, "rb") as f:
        return tomllib.load(f)


def site() -> dict:
    return load_toml("site_86field.toml")
