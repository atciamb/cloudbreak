"""Human approval: one-time codes and single-use HMAC tokens.

Flow: prepare() -> OTP printed ONLY on the governor's console (a human must read it) -> operator types
OTP + "LAND <hash4>" on the governor's own page -> mint() returns a token bound to
(mission_hash, candidate_id, grid_version, target, sysid, operator, iat, exp, nonce). The HMAC key is
generated at governor start-up and never leaves the governor process. Tokens are single use.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass

TOKEN_TTL_S = 120
OTP_TTL_S = 300
OTP_MAX_TRIES = 3


@dataclass
class Pending:
    mission_hash: str
    candidate_id: str
    grid_version: int
    target: str
    sysid: int
    kind: str
    otp: str
    otp_exp: float
    tries: int = 0


@dataclass
class Token:
    mission_hash: str
    candidate_id: str
    grid_version: int
    target: str
    sysid: int
    kind: str
    operator: str
    iat: float
    exp: float
    nonce: str
    mac: str = ""

    def body(self) -> bytes:
        d = asdict(self)
        d.pop("mac")
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


class Approvals:
    def __init__(self):
        self._key = os.urandom(32)          # in memory only
        self.pending: Pending | None = None
        self.used: set[str] = set()

    def prepare(self, mission_hash, candidate_id, grid_version, target, sysid, kind) -> Pending:
        otp = f"{secrets.randbelow(10 ** 6):06d}"
        self.pending = Pending(mission_hash, candidate_id, grid_version, target, sysid, kind, otp, time.time() + OTP_TTL_S)
        return self.pending

    def mint(self, mission_hash: str, otp: str, confirm: str, operator: str) -> Token:
        p = self.pending
        if p is None:
            raise PermissionError("nothing prepared")
        if time.time() > p.otp_exp:
            self.pending = None
            raise PermissionError("one-time code expired; prepare again")
        if p.tries >= OTP_MAX_TRIES:
            self.pending = None
            raise PermissionError("too many wrong codes; prepare again")
        if mission_hash != p.mission_hash:
            raise PermissionError("approval is for a different mission")
        if not hmac.compare_digest(otp.strip(), p.otp):
            p.tries += 1
            raise PermissionError(f"wrong one-time code ({OTP_MAX_TRIES - p.tries} tries left)")
        expected = f"LAND {p.mission_hash[:4]}" if p.kind == "landing" else f"FLY {p.mission_hash[:4]}"
        if confirm.strip().upper() != expected.upper():
            p.tries += 1
            raise PermissionError(f"confirmation must read '{expected}'")
        if not operator.strip():
            raise PermissionError("operator name required")
        now = time.time()
        t = Token(p.mission_hash, p.candidate_id, p.grid_version, p.target, p.sysid, p.kind, operator.strip(), now,
                  now + TOKEN_TTL_S, secrets.token_hex(8))
        t.mac = hmac.new(self._key, t.body(), hashlib.sha256).hexdigest()
        self.pending = None
        return t

    def verify(self, t: Token) -> tuple[bool, str]:
        good = hmac.compare_digest(hmac.new(self._key, t.body(), hashlib.sha256).hexdigest(), t.mac)
        if not good:
            return False, "bad signature"
        if t.nonce in self.used:
            return False, "token already used"
        if time.time() > t.exp:
            return False, "token expired"
        return True, "ok"

    def consume(self, t: Token):
        self.used.add(t.nonce)
