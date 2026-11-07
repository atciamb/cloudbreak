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


DEFAULT_SITE = "86field"


def site_key() -> str:
    """Active site: CLOUDBREAK_SITE env var (default '86field'); config file config/site_<key>.toml."""
    return os.environ.get("CLOUDBREAK_SITE", DEFAULT_SITE)


def set_site(key: str) -> None:
    if not (CONFIG_DIR / f"site_{key}.toml").exists():
        raise FileNotFoundError(f"no config/site_{key}.toml")
    os.environ["CLOUDBREAK_SITE"] = key


def priors_dir(kind: str = "") -> Path:
    """Per-site priors folder. The original '86 Field site keeps C:\\cb-data\\priors; others use priors\\sites\\<key>."""
    base = data_dir() / "priors" if site_key() == DEFAULT_SITE else data_dir() / "priors" / "sites" / site_key()
    p = base / kind if kind else base
    p.mkdir(parents=True, exist_ok=True)
    return p


@lru_cache(maxsize=None)
def load_toml(name: str) -> dict:
    path = CONFIG_DIR / name
    with open(path, "rb") as f:
        return tomllib.load(f)


def site() -> dict:
    return load_toml(f"site_{site_key()}.toml")
