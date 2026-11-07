from cloudbreak.governor import Approval, LinkStatus, check, mission_hash
from cloudbreak.planner import Waypoint

MISSION = (
    Waypoint(42.7300, -73.6780, 40.0),
    Waypoint(42.7305, -73.6775, 20.0),
    Waypoint(42.7310, -73.6770, 0.0),
)
NOW = 1_000_000.0
HEALTHY = LinkStatus(heartbeat_ok=True, telemetry_age_s=0.3)


def approval(**overrides):
    fields = dict(mission_hash=mission_hash(MISSION), approved_by="andrew", expires_at=NOW + 60)
    fields.update(overrides)
    return Approval(**fields)


def test_valid_approval_passes():
    assert check(MISSION, approval(), HEALTHY, NOW) == []


def test_missing_approval_is_refused():
    assert "no human approval" in check(MISSION, None, HEALTHY, NOW)


def test_mission_edited_after_approval_is_refused():
    edited = MISSION[:-1] + (Waypoint(42.7311, -73.6770, 0.0),)
    assert "mission changed since it was approved" in check(edited, approval(), HEALTHY, NOW)


def test_expired_approval_is_refused():
    assert "approval has expired" in check(MISSION, approval(expires_at=NOW - 1), HEALTHY, NOW)


def test_agent_cannot_approve():
    problems = check(MISSION, approval(approved_by="agent"), HEALTHY, NOW)
    assert any("must come from a human" in p for p in problems)


def test_unhealthy_link_is_refused():
    stale = LinkStatus(heartbeat_ok=False, telemetry_age_s=9.0)
    problems = check(MISSION, approval(), stale, NOW)
    assert "no autopilot heartbeat" in problems
    assert any("telemetry is 9.0 s old" in p for p in problems)
