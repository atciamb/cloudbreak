"""Landing-candidate planner: ranks strips and approach paths. Runs on the laptop.

Not implemented yet. The planner proposes; it never approves. Ranking will
account for strip geometry, obstacles, map evidence and (when defensible) wind,
and must check the whole path (turns, approach, go-around), not just waypoints.
"""

from __future__ import annotations

from dataclasses import dataclass

from cloudbreak.landability import LandabilityGrid


@dataclass(frozen=True)
class Waypoint:
    lat: float  # degrees
    lon: float  # degrees
    alt_m: float  # metres relative to home


@dataclass(frozen=True)
class Candidate:
    """One candidate landing strip and the mission that flies to it."""

    id: str
    heading_deg: float
    length_m: float
    mission: tuple[Waypoint, ...]  # approach through touchdown
    score: float = 0.0
    reasons: tuple[str, ...] = ()  # human-readable evidence for the score


def rank_candidates(grid: LandabilityGrid) -> list[Candidate]:
    """Return candidates best-first. Not written yet."""
    raise NotImplementedError("planner not implemented yet")
