"""Deterministic go/no-go checks. Pure functions of their inputs -- no I/O, no clocks except values passed in.

Every check returns Check(name, ok, value, limit, detail). The governor executes only if ALL pass.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

EKF_ATTITUDE, EKF_VEL_H, EKF_POS_H_ABS, EKF_POS_V_ABS, EKF_CONST_POS, EKF_UNINIT = 1, 2, 16, 32, 128, 1024


@dataclass
class Check:
    name: str
    ok: bool
    value: object = None
    limit: object = None
    detail: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Snapshot:
    """Telemetry snapshot taken by the governor from its own (signed, read-write) link."""
    sysid: int | None = None
    hb_age_s: float = float("inf")
    pos_age_s: float = float("inf")
    att_age_s: float = float("inf")
    loss_rate: float = 1.0
    rtt_ms: float | None = None
    fix_type: int = 0
    sats: int = 0
    hdop: float = 99.0
    ekf_flags: int | None = None
    battery_pct: int | None = None
    mode: str = "?"
    armed: bool = False
    rel_alt_m: float | None = None
    rc: list = field(default_factory=list)
    sim_param_present: bool | None = None
    board: str | None = None
    firmware: str | None = None


@dataclass
class Context:
    phase: str                       # "upload" | "commit"
    kind: str                        # "landing" | "survey"
    target_name: str
    target: dict
    snap: Snapshot
    token_ok: bool = False
    token_reason: str = ""
    token_hash: str | None = None
    token_target: str | None = None
    token_sysid: int | None = None
    token_grid_version: int | None = None
    rebuilt_hash: str | None = None
    grid_version_now: int | None = None
    site_valid: bool = False
    site_reason: str = ""
    last_look_views: int = 0
    bias_drift_m: float | None = None
    geometry_ok: bool = False
    geometry_reason: str = ""
    gates: dict = field(default_factory=dict)
    param_audit: dict = field(default_factory=dict)   # name -> (value, expected, ok)


def run_checks(c: Context) -> list[Check]:
    s, t = c.snap, c.target
    out: list[Check] = []
    add = lambda *a, **k: out.append(Check(*a, **k))

    if c.phase == "upload":
        add("token_valid", c.token_ok, c.token_reason)
        add("token_bound_to_mission", c.token_hash is not None and c.token_hash == c.rebuilt_hash,
            (c.token_hash or "")[:12], (c.rebuilt_hash or "")[:12], "token hash must equal the governor's fresh rebuild")
        add("token_bound_to_target", c.token_target == c.target_name and c.token_sysid == t["sysid"],
            f"{c.token_target}/{c.token_sysid}", f"{c.target_name}/{t['sysid']}")
        if c.kind == "landing":
            add("grid_version_current", c.token_grid_version == c.grid_version_now, c.token_grid_version,
                c.grid_version_now, "map changed since approval -> re-plan and re-approve")

    # target fingerprint
    if t["fingerprint"] == "sitl":
        add("fingerprint_sitl", s.sim_param_present is True, s.sim_param_present, True, "SIM_SPEEDUP must exist")
    else:
        add("fingerprint_real_no_sim_params", s.sim_param_present is False, s.sim_param_present, False)
        add("fingerprint_board", bool(s.board) and t.get("board_substr", "") in (s.board or ""), s.board, t.get("board_substr"))
        add("fingerprint_firmware", bool(s.firmware) and t.get("firmware_version", "") in (s.firmware or ""), s.firmware,
            t.get("firmware_version"))
    add("sysid", s.sysid == t["sysid"], s.sysid, t["sysid"])

    # link health
    add("heartbeat_fresh", s.hb_age_s < 1.5, round(s.hb_age_s, 2), 1.5)
    add("telemetry_fresh", s.pos_age_s < 1.0 and s.att_age_s < 1.0, round(max(s.pos_age_s, s.att_age_s), 2), 1.0)
    add("packet_loss", s.loss_rate < 0.05, round(s.loss_rate, 3), 0.05)
    add("round_trip", s.rtt_ms is not None and s.rtt_ms < t.get("max_rtt_ms", 500), s.rtt_ms, t.get("max_rtt_ms", 500))

    # navigation health
    add("gps_fix", s.fix_type >= 3, s.fix_type, ">=3")
    add("gps_sats", s.sats >= 8, s.sats, ">=8")
    add("gps_hdop", s.hdop <= 2.0, s.hdop, "<=2.0")
    need = EKF_ATTITUDE | EKF_VEL_H | EKF_POS_H_ABS | EKF_POS_V_ABS
    ekf_ok = s.ekf_flags is not None and (s.ekf_flags & need) == need and not (s.ekf_flags & (EKF_CONST_POS | EKF_UNINIT))
    add("ekf_healthy", ekf_ok, s.ekf_flags, f"has {need}, not {EKF_CONST_POS | EKF_UNINIT}")
    if s.battery_pct is not None and s.battery_pct >= 0:
        add("battery", s.battery_pct >= 30, s.battery_pct, ">=30%")

    if c.kind == "landing":
        add("airborne", s.armed and (s.rel_alt_m or 0) > 15, f"armed={s.armed} alt={s.rel_alt_m}", "armed, >15 m")
        add("site_valid", c.site_valid, c.site_reason)
        add("path_clearance_and_fence", c.geometry_ok, c.geometry_reason)
    else:
        add("path_clearance_and_fence", c.geometry_ok, c.geometry_reason)

    if c.phase == "commit":
        add("mode_auto", s.mode == "AUTO", s.mode, "AUTO")
        add("last_look_views", c.last_look_views >= 3, c.last_look_views, ">=3 fresh views of the strip during hold")
        if c.bias_drift_m is not None:
            add("baro_bias_drift", abs(c.bias_drift_m) <= 0.5, round(c.bias_drift_m, 2), "<=0.5 m since approval")

    # real-aircraft-only gates
    if t["fingerprint"] == "real":
        ch = int(t.get("consent_channel", 0))
        val = s.rc[ch - 1] if ch and len(s.rc) >= ch else None
        add("pilot_consent_switch", val is not None and val > t.get("consent_pwm", 1700), val, f"RC{ch} > {t.get('consent_pwm')}")
        req = t.get("required_gates" if c.kind == "landing" else "required_gates_survey", [])
        missing = [g for g in req if not c.gates.get(g, {}).get("passed")]
        add("flight_gates_passed", not missing, missing or "all", req)
        bad = {k: v for k, v in c.param_audit.items() if not v[2]}
        add("param_audit", bool(c.param_audit) and not bad, bad or "all match", "targets.toml [real.param_audit]")
    return out


def all_ok(checks: list[Check]) -> bool:
    return bool(checks) and all(ch.ok for ch in checks)
