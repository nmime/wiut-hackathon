#!/usr/bin/env python3
"""Restore only into a generated disposable database, never the live target."""

from __future__ import annotations

import argparse
import os
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from backup import validate_archive
from common import (
    STATE,
    OperationError,
    atomic_json,
    compose,
    environment,
    lock,
    private_directory,
    run,
)


def verify(path: Path) -> dict:
    environment()
    if path.is_symlink() or not path.is_file():
        raise OperationError("Backup must be a regular archive file")
    manifest = validate_archive(path)
    name = f"flowcredit_restore_check_{os.urandom(8).hex()}"
    created = False
    with lock("deploy.lock"):
        try:
            run(compose("exec", "-T", "db", "createdb", "-U", "wiut", name))
            created = True
            with (
                tarfile.open(path, "r:gz") as archive,
                tempfile.TemporaryFile() as dump,
            ):
                source = archive.extractfile("database.dump")
                if source is None:
                    raise OperationError("Database dump missing")
                while chunk := source.read(1024 * 1024):
                    dump.write(chunk)
                dump.seek(0)
                run(
                    compose(
                        "exec",
                        "-T",
                        "db",
                        "pg_restore",
                        "-U",
                        "wiut",
                        "--exit-on-error",
                        "--single-transaction",
                        "--no-owner",
                        "--no-acl",
                        "-d",
                        name,
                    ),
                    stdin=dump,
                    timeout=1800,
                )
            counts = run(
                compose(
                    "exec",
                    "-T",
                    "db",
                    "psql",
                    "-U",
                    "wiut",
                    "-d",
                    name,
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-At",
                    "-c",
                    "SELECT json_build_object('users',(SELECT count(*) FROM app_users),'tenants',(SELECT count(*) FROM tenants),'businesses',(SELECT count(*) FROM businesses),'assessments',(SELECT count(*) FROM assessments),'decisions',(SELECT count(*) FROM decisions),'audit_events',(SELECT count(*) FROM audit_events))",
                )
            )
            import json

            return {
                "status": "ok",
                "verified_at": datetime.now(UTC).isoformat(),
                "archive": path.name,
                "restored_counts": json.loads(counts),
                "audit_snapshots": manifest["audit_snapshots"],
            }
        finally:
            if created:
                # The target is generated here and cannot be supplied by callers.
                run(compose("exec", "-T", "db", "dropdb", "-U", "wiut", name))


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    options = parser.parse_args()
    private_directory(STATE)
    try:
        status = verify(options.archive.absolute())
        atomic_json(STATE / "restore-status.json", status)
        print(
            "Backup checksums and disposable PostgreSQL restoration passed; the live database was untouched."
        )
        return 0
    except (OperationError, OSError, ValueError, tarfile.TarError):
        atomic_json(
            STATE / "restore-status.json",
            {"status": "failed", "observed_at": datetime.now(UTC).isoformat()},
        )
        print(
            "Backup restoration verification failed. Inspect operation state; no live restore was attempted.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
