"""Deterministic pre-upload checks for a human-approved mission. Runs on the laptop.

The governor is meant to be the only path that hands a mission to the
autopilot. It never chooses which plan to fly; it refuses plans that are
unapproved, changed after approval, expired, or sent over an unhealthy link.

Approval is bound to the exact mission (by hash) and expires. Further link
checks (sequence gaps, round-trip latency, loss) are still to be added.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Sequence

from cloudbreak.planner import Waypoint

# Identities that may propose but must never approve. This catches obvious
# mistakes; it is not access control. Real separation means the agent process
# has no way to create an Approval (only the operator UI does).
NON_APPROVERS = frozenset({"agent", "planner", "governor"})


def mission_hash(mission: Sequence[Waypoint]) -> str:
    """Hash of the exact waypoint list; any change produces a new hash."""
    canonical = json.dumps([[w.lat, w.lon, w.alt_m] for w in mission])
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class Approval:
    mission_hash: str
    approved_by: str  # the human operator
    expires_at: float  # Unix time, seconds


@dataclass(frozen=True)
class LinkStatus:
    heartbeat_ok: bool
    telemetry_age_s: float  # seconds since the last autopilot message


@dataclass(frozen=True)
class Limits:
    max_telemetry_age_s: float = 2.0  # placeholder; tune on the bench


def check(
    mission: Sequence[Waypoint],
    approval: Approval | None,
    link: LinkStatus,
    now: float,
    limits: Limits = Limits(),
) -> list[str]:
    """Return the reasons to refuse upload. An empty list means it may proceed."""
    problems = []

    if not mission:
        problems.append("mission is empty")

    if approval is None:
        problems.append("no human approval")
    else:
        who = approval.approved_by.strip().lower()
        if not who or who in NON_APPROVERS:
            problems.append(f"approval must come from a human, not {approval.approved_by!r}")
        if approval.mission_hash != mission_hash(mission):
            problems.append("mission changed since it was approved")
        if now >= approval.expires_at:
            problems.append("approval has expired")

    if not link.heartbeat_ok:
        problems.append("no autopilot heartbeat")
    if link.telemetry_age_s > limits.max_telemetry_age_s:
        problems.append(
            f"telemetry is {link.telemetry_age_s:.1f} s old "
            f"(limit {limits.max_telemetry_age_s:.1f} s)"
        )

    return problems
