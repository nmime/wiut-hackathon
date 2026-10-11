"""Private append-only JSONL evidence, fsynced under an interprocess file lock.

This is durable local audit storage, not a claim of tamper-proof external anchoring.
The Nest database remains the authority for tenant access and officer decisions.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path


class DurableAudit:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Fail startup if durable storage cannot be opened. fsync the directory
        # when first creating the log, so its directory entry is durable too.
        existed = self.path.exists()
        descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.close(descriptor)
        if not existed:
            parent = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)

    def append(self, record: dict):
        data = {
            "logged_at": datetime.now(UTC).isoformat(),
            **record,
        }
        encoded = (
            json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            + "\n"
        ).encode()
        descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("Incomplete audit append")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class VendorResponseCollector:
    """Capture unchanged vendor responses for the wrapper's durable completion log."""

    def __init__(self):
        self.records: list[dict] = []

    def append(self, kind: str, request_id: str, payload: dict):
        record = {"type": kind, "request_id": request_id, "payload": payload}
        self.records.append(record)
        return record
