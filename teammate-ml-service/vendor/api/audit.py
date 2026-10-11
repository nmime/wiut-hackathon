"""Журнал аудита: только дозапись (JSONL) с цепочкой хэшей.

Каждая запись содержит hash предыдущей; подмена или удаление строки обнаруживается
проверкой verify(). По request_id восстанавливается полный ответ и история решений офицера.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._assessments: dict[str, int] = {}   # request_id -> смещение строки в файле
        self._decisions: dict[str, list[int]] = {}
        self._other: dict[str, int] = {}             # отклонённый ввод и прочие записи
        self._last_hash = GENESIS
        self._reindex()

    def _reindex(self):
        if not self.path.exists():
            return
        with open(self.path, "rb") as f:
            while True:
                off = f.tell()
                line = f.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                rec = json.loads(line)
                self._index(rec, off)
                self._last_hash = rec["hash"]

    def _index(self, rec: dict, off: int):
        if rec["type"] == "assessment":
            self._assessments[rec["request_id"]] = off
        elif rec["type"] == "decision":
            self._decisions.setdefault(rec["request_id"], []).append(off)
        else:  # input_rejected и прочие типы
            self._other[rec["request_id"]] = off

    def append(self, rec_type: str, request_id: str, payload: dict) -> dict:
        with self._lock:
            rec = dict(type=rec_type, request_id=request_id,
                       logged_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                       prev_hash=self._last_hash, payload=payload)
            rec["hash"] = hashlib.sha256(_canon(rec).encode("utf-8")).hexdigest()
            line = (_canon(rec) + "\n").encode("utf-8")
            with open(self.path, "ab") as f:
                off = f.tell()
                f.write(line)
                f.flush()
            self._index(rec, off)
            self._last_hash = rec["hash"]
            return rec

    def _read_at(self, off: int) -> dict:
        with open(self.path, "rb") as f:
            f.seek(off)
            return json.loads(f.readline())

    def get(self, request_id: str) -> dict | None:
        off = self._assessments.get(request_id)
        if off is None:
            return None
        rec = self._read_at(off)
        rec["decisions"] = [self._read_at(o) for o in self._decisions.get(request_id, [])]
        return rec

    def get_any(self, request_id: str) -> dict | None:
        if request_id in self._assessments:
            return self.get(request_id)
        off = self._other.get(request_id)
        return None if off is None else self._read_at(off)

    def counts(self) -> dict:
        return dict(assessments=len(self._assessments), input_rejected=len(self._other),
                    decisions=sum(len(v) for v in self._decisions.values()))

    def verify(self) -> dict:
        prev, n = GENESIS, 0
        if not self.path.exists():
            return dict(ok=True, records=0)
        with open(self.path, "rb") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                rec = json.loads(line)
                h = rec.pop("hash")
                if rec["prev_hash"] != prev or hashlib.sha256(_canon(rec).encode("utf-8")).hexdigest() != h:
                    return dict(ok=False, records=n, broken_at_line=i)
                prev, n = h, n + 1
        return dict(ok=True, records=n)
