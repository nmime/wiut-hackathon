#!/usr/bin/env python3
"""Verified private database/audit/config snapshots with narrow retention."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from common import (
    BACKUPS,
    ENVIRONMENT,
    ROOT,
    STATE,
    OperationError,
    atomic_json,
    checksum,
    compose,
    environment,
    fsync_directory,
    lock,
    private_directory,
    run,
)

OWNED_ARCHIVE = re.compile(r"flowcredit-scheduled-\d{8}T\d{6}Z-[a-f0-9]{16}\.tar\.gz")
MAX_AUDIT_ROW_BYTES = 16 * 1024 * 1024
# Execute in an existing pinned local Python image, without application startup,
# network, capabilities or a writable audit volume. A shared flock coordinates
# with the teammate writer; the default writer uses individual durable appends.
SNAPSHOT_CODE = r"""
import fcntl,json,os,sys,time
path='/snapshot/requests.jsonl'
with open(path,'rb') as source:
    deadline=time.monotonic()+10
    while True:
        try:
            fcntl.flock(source,fcntl.LOCK_SH|fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic()>deadline: raise RuntimeError('Audit snapshot lock timeout')
            time.sleep(.05)
    size=os.fstat(source.fileno()).st_size
    captured=rows=consumed=0
    while consumed<size:
        row=source.readline(min(size-consumed,16*1024*1024+1))
        if not row: raise RuntimeError('Audit was truncated while snapshotting')
        consumed+=len(row)
        if len(row)>16*1024*1024: raise RuntimeError('Audit row exceeds bound')
        if not row.endswith(b'\n'):
            if consumed!=size: raise RuntimeError('Audit row exceeds bound')
            break
        if not isinstance(json.loads(row),dict): raise RuntimeError('Invalid audit record')
        sys.stdout.buffer.write(row)
        captured+=len(row); rows+=1
    sys.stdout.buffer.flush()
    print(json.dumps({'snapshot_size_bytes':size,'captured_bytes':captured,'records':rows,'omitted_partial_tail_bytes':size-captured}),file=sys.stderr)
"""


def validate_archive(path: Path) -> dict:
    """Read every member and hash it; never extract credentials to a loose path."""
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        allowed = {
            "database.dump",
            ".env.production",
            "ml-audit.jsonl",
            "teammate-ml-audit.jsonl",
            "manifest.json",
        }
        if (
            len(names) != len(set(names))
            or not set(names) <= allowed
            or not {"database.dump", ".env.production", "manifest.json"} <= set(names)
            or any(not member.isfile() or member.mode != 0o600 for member in members)
        ):
            raise OperationError("Backup archive structure is invalid")
        metadata_stream = archive.extractfile("manifest.json")
        if metadata_stream is None:
            raise OperationError("Backup manifest missing")
        manifest = json.load(metadata_stream)
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != set(names) - {"manifest.json"}:
            raise OperationError("Backup manifest does not match its members")
        for name, expected in files.items():
            stream = archive.extractfile(name)
            if (
                stream is None
                or not isinstance(expected, str)
                or hashlib.file_digest(stream, "sha256").hexdigest() != expected
            ):
                raise OperationError("Backup checksum verification failed")
        return manifest


def retain(directory: Path, keep_days: int, now: float) -> int:
    removed = 0
    cutoff = now - keep_days * 86400
    for path in directory.iterdir():
        if (
            OWNED_ARCHIVE.fullmatch(path.name)
            and not path.is_symlink()
            and path.is_file()
            and path.stat().st_mtime < cutoff
        ):
            path.unlink()
            removed += 1
    if removed:
        fsync_directory(directory)
    return removed


def snapshot_audit(image: str, volume: str, target: Path) -> dict:
    with target.open("wb") as output:
        process_environment = os.environ.copy()
        for key in environment():
            process_environment.pop(key, None)
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                "10001:10001",
                "--volume",
                f"{volume}:/snapshot:ro",
                "--entrypoint",
                "python",
                image,
                "-c",
                SNAPSHOT_CODE,
            ],
            cwd=ROOT,
            env=process_environment,
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
        output.flush()
        os.fsync(output.fileno())
    if result.returncode:
        raise OperationError("Audit snapshot failed; no archive or retention published")
    try:
        metadata = json.loads(result.stderr)
    except ValueError as error:
        raise OperationError("Audit snapshot metadata is invalid") from error
    if metadata.get("captured_bytes") != target.stat().st_size:
        raise OperationError("Audit snapshot length is inconsistent")
    return metadata


def create_backup(keep_days: int) -> Path:
    environment()
    private_directory(BACKUPS)
    with (
        lock("deploy.lock"),
        tempfile.TemporaryDirectory(prefix=".pending-", dir=BACKUPS) as temporary,
    ):
        staging = Path(temporary)
        manifest: dict = {
            "format": "flowcredit-backup-v1",
            "created_at": datetime.now(UTC).isoformat(),
            "audit_snapshots": {},
            "files": {},
        }
        with (staging / "database.dump").open("wb") as output:
            run(
                compose(
                    "exec",
                    "-T",
                    "db",
                    "pg_dump",
                    "-U",
                    "wiut",
                    "-d",
                    "wiut",
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                ),
                stdout=output,
                timeout=1800,
            )
            output.flush()
            os.fsync(output.fileno())
        with (staging / "database.dump").open("rb") as source:
            run(
                compose("exec", "-T", "db", "pg_restore", "--list"),
                stdin=source,
                timeout=120,
            )
        # The fixed project/service build tag is owned by this Compose stack.
        # A running container can retain its filesystem after Docker removes its
        # old image metadata, making `compose images` fail during an update.
        # The helper needs only stdlib Python, not that serving model's image.
        # Resolve the already-built local tag to an immutable full ID; never pull.
        image = (
            run(["docker", "image", "inspect", "--format", "{{.Id}}", "flowcredit-ml"])
            .decode()
            .strip()
        )
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise OperationError("Cannot identify the installed local Python image")
        volumes = set(run(["docker", "volume", "ls", "--quiet"]).decode().split())
        for service in ("ml", "teammate-ml"):
            volume = f"flowcredit_{service}-audit"
            if volume not in volumes:
                if service == "ml":
                    raise OperationError("Required ML audit volume missing")
                manifest["audit_snapshots"][service] = {"volume_present": False}
                continue
            manifest["audit_snapshots"][service] = {
                "volume_present": True,
                **snapshot_audit(image, volume, staging / f"{service}-audit.jsonl"),
            }
        shutil.copyfile(ENVIRONMENT, staging / ".env.production")
        for path in staging.iterdir():
            path.chmod(0o600)
            manifest["files"][path.name] = checksum(path)
        atomic_json(staging / "manifest.json", manifest)
        name = f"flowcredit-scheduled-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{os.urandom(8).hex()}.tar.gz"
        destination = BACKUPS / name
        pending = BACKUPS / f".{name}.part"
        try:
            with tarfile.open(pending, "w:gz") as archive:
                for path in sorted(staging.iterdir()):
                    archive.add(path, arcname=path.name, recursive=False)
            pending.chmod(0o600)
            validate_archive(pending)
            with pending.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(pending, destination)
            fsync_directory(BACKUPS)
            removed = retain(BACKUPS, keep_days, time.time())
            atomic_json(
                STATE / "backup-status.json",
                {
                    "status": "ok",
                    "completed_at": datetime.now(UTC).isoformat(),
                    "archive": name,
                    "archive_sha256": checksum(destination),
                    "retention_days": keep_days,
                    "retained_old_archives_removed": removed,
                    "audit_snapshots": manifest["audit_snapshots"],
                },
            )
            return destination
        finally:
            pending.unlink(missing_ok=True)


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-days", type=int, default=14)
    options = parser.parse_args()
    if not 1 <= options.keep_days <= 365:
        parser.error("Retention must be between 1 and 365 days")
    try:
        destination = create_backup(options.keep_days)
        print(f"Private verified backup saved: {destination.name}")
        return 0
    except (
        OperationError,
        OSError,
        ValueError,
        tarfile.TarError,
        subprocess.TimeoutExpired,
    ) as error:
        atomic_json(
            STATE / "backup-status.json",
            {
                "status": "failed",
                "observed_at": datetime.now(UTC).isoformat(),
                "reason": type(error).__name__,
            },
        )
        print(
            "Backup operation failed. Retention is never attempted before a new archive passes verification. Inspect the host operation and container state.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
