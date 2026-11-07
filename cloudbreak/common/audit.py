"""Append-only, hash-chained JSONL audit log.

Each record: {seq, t, actor, event, data, prev_hash, hash} where hash = sha256(prev_hash + canonical(record
without hash)). Any edit or deletion breaks the chain; `verify()` reports the first bad record.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class AuditLog:
    def __init__(self, path: str | Path, actor: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.actor = actor
        self._lock = threading.Lock()
        self.seq, self.prev = 0, "0" * 64
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.seq, self.prev = r["seq"] + 1, r["hash"]

    def log(self, event: str, **data) -> dict:
        with self._lock:
            rec = dict(seq=self.seq, t=time.time(), actor=self.actor, event=event, data=data, prev_hash=self.prev)
            rec["hash"] = hashlib.sha256((self.prev + _canon(rec)).encode()).hexdigest()
            with open(self.path, "a") as f:
                f.write(_canon(rec) + "\n")
            self.seq += 1
            self.prev = rec["hash"]
            return rec

    @staticmethod
    def verify(path: str | Path) -> tuple[bool, int | None]:
        prev = "0" * 64
        for i, line in enumerate(Path(path).read_text().splitlines()):
            r = json.loads(line)
            h = r.pop("hash")
            if r["prev_hash"] != prev or hashlib.sha256((prev + _canon(r)).encode()).hexdigest() != h:
                return False, i
            prev = h
        return True, None

    def tail(self, n: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines()[-n:]]
