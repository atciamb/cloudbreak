import time

import pytest

from cloudbreak.ground.governor.approval import Approvals
from cloudbreak.ground.governor.checks import Context, Snapshot, all_ok, run_checks
from cloudbreak.ground.governor.governor import load_targets

TARGETS = load_targets()


def good_snap(**kw):
    s = dict(sysid=1, hb_age_s=0.3, pos_age_s=0.1, att_age_s=0.05, loss_rate=0.0, rtt_ms=40, fix_type=3, sats=12,
             hdop=0.8, ekf_flags=1 | 2 | 4 | 8 | 16 | 32, battery_pct=80, mode="AUTO", armed=True, rel_alt_m=40.0,
             rc=[1500] * 18, sim_param_present=True)
    s.update(kw)
    return Snapshot(**s)


def good_ctx(phase="upload", target="sitl", **kw):
    t = TARGETS[target]
    c = dict(phase=phase, kind="landing", target_name=target, target=t, snap=good_snap(sysid=t["sysid"]),
             token_ok=True, token_reason="ok", token_hash="h" * 64, token_target=target, token_sysid=t["sysid"],
             token_grid_version=3, rebuilt_hash="h" * 64, grid_version_now=3, site_valid=True, site_reason="ok",
             last_look_views=4, bias_drift_m=0.1, geometry_ok=True, geometry_reason="ok")
    c.update(kw)
    return Context(**c)


def failing(ctx):
    return {c.name for c in run_checks(ctx) if not c.ok}


def test_all_good_passes():
    assert all_ok(run_checks(good_ctx()))
    assert all_ok(run_checks(good_ctx(phase="commit")))


@pytest.mark.parametrize("change,expect", [
    (dict(token_ok=False, token_reason="token expired"), "token_valid"),
    (dict(rebuilt_hash="x" * 64), "token_bound_to_mission"),
    (dict(token_target="real"), "token_bound_to_target"),
    (dict(token_grid_version=2), "grid_version_current"),
    (dict(site_valid=False, site_reason="person on strip"), "site_valid"),
    (dict(geometry_ok=False, geometry_reason="below clearance"), "path_clearance_and_fence"),
])
def test_refusals_context(change, expect):
    assert expect in failing(good_ctx(**change))


@pytest.mark.parametrize("snapchange,expect", [
    (dict(hb_age_s=3.0), "heartbeat_fresh"),
    (dict(pos_age_s=2.0), "telemetry_fresh"),
    (dict(loss_rate=0.2), "packet_loss"),
    (dict(rtt_ms=None), "round_trip"),
    (dict(fix_type=2), "gps_fix"),
    (dict(ekf_flags=1 | 2 | 16 | 32 | 128), "ekf_healthy"),
    (dict(battery_pct=10), "battery"),
    (dict(armed=False), "airborne"),
    (dict(sim_param_present=False), "fingerprint_sitl"),
    (dict(sysid=42), "sysid"),
])
def test_refusals_snapshot(snapchange, expect):
    ctx = good_ctx()
    ctx.snap = good_snap(**{**dict(sysid=1), **snapchange})
    assert expect in failing(ctx)


def test_commit_requires_last_look_and_auto_and_bias():
    assert "last_look_views" in failing(good_ctx(phase="commit", last_look_views=2))
    ctx = good_ctx(phase="commit")
    ctx.snap = good_snap(mode="FBWA")
    assert "mode_auto" in failing(ctx)
    assert "baro_bias_drift" in failing(good_ctx(phase="commit", bias_drift_m=0.9))


def test_real_target_requires_gates_consent_and_param_audit():
    t = TARGETS["real"]
    ctx = good_ctx(target="real")
    ctx.snap = good_snap(sysid=42, sim_param_present=False, board="CoreWingF405WMiniV2 0042", firmware="4.7.2")
    f = failing(ctx)
    assert {"flight_gates_passed", "param_audit", "pilot_consent_switch"} <= f
    rc = [1500] * 18
    rc[t["consent_channel"] - 1] = 1900
    ctx.snap = good_snap(sysid=42, sim_param_present=False, board="CoreWingF405WMiniV2 0042", firmware="4.7.2", rc=rc)
    ctx.gates = {g: {"passed": True} for g in t["required_gates"]}
    ctx.param_audit = {k: (v[0], v[0], True) for k, v in t["param_audit"].items()}
    assert all_ok(run_checks(ctx))


def test_real_target_rejects_sitl_fingerprint():
    ctx = good_ctx(target="real")
    ctx.snap = good_snap(sysid=42, sim_param_present=True)
    assert "fingerprint_real_no_sim_params" in failing(ctx)


# ---------------------------------------------------------------- approvals
def test_otp_flow_and_single_use():
    a = Approvals()
    p = a.prepare("ab12" + "0" * 60, "C1", 3, "sitl", 1, "landing")
    with pytest.raises(PermissionError):
        a.mint(p.mission_hash, "000000" if p.otp != "000000" else "111111", "LAND ab12", "op")
    with pytest.raises(PermissionError):
        a.mint(p.mission_hash, p.otp, "LAND zzzz", "op")
    t = a.mint(p.mission_hash, p.otp, "land ab12", "Andrew")
    assert a.verify(t) == (True, "ok")
    a.consume(t)
    assert a.verify(t)[0] is False


def test_otp_lockout_after_three_tries():
    a = Approvals()
    p = a.prepare("cd34" + "0" * 60, "C1", 1, "sitl", 1, "landing")
    wrong = "999999" if p.otp != "999999" else "888888"
    for _ in range(3):
        with pytest.raises(PermissionError):
            a.mint(p.mission_hash, wrong, "LAND cd34", "op")
    with pytest.raises(PermissionError):
        a.mint(p.mission_hash, p.otp, "LAND cd34", "op")       # locked out even with the right code


def test_token_tamper_and_expiry():
    a = Approvals()
    p = a.prepare("ef56" + "0" * 60, "C1", 1, "sitl", 1, "landing")
    t = a.mint(p.mission_hash, p.otp, "LAND ef56", "op")
    t.candidate_id = "C2"
    assert a.verify(t) == (False, "bad signature")
    p = a.prepare("ef56" + "0" * 60, "C1", 1, "sitl", 1, "landing")
    t = a.mint(p.mission_hash, p.otp, "LAND ef56", "op")
    t2 = t
    t2.exp = time.time() - 1          # tampering with exp also breaks the MAC
    assert a.verify(t2)[0] is False


def test_tokens_from_another_governor_instance_rejected():
    a, b = Approvals(), Approvals()
    p = a.prepare("aa11" + "0" * 60, "C1", 1, "sitl", 1, "landing")
    t = a.mint(p.mission_hash, p.otp, "LAND aa11", "op")
    assert b.verify(t) == (False, "bad signature")
