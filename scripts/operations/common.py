"""Local production operations. Environment files are data, never shell code."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "artifacts" / "operations"
BACKUPS = ROOT / "artifacts" / "scheduled-backups"
ENVIRONMENT = ROOT / ".env.production"


class OperationError(RuntimeError):
    pass


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise OperationError("Private operation directory must not be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def environment() -> dict[str, str]:
    if ENVIRONMENT.is_symlink() or not ENVIRONMENT.is_file():
        raise OperationError("Missing regular .env.production file")
    if ENVIRONMENT.stat().st_mode & 0o077:
        raise OperationError(".env.production must have permissions 600")
    values: dict[str, str] = {}
    for line in ENVIRONMENT.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.*)", line)
        if not match or match[1] in values:
            raise OperationError("Invalid or duplicate production environment key")
        values[match[1]] = match[2]
    domain = values.get("DOMAIN", "")
    labels = domain.split(".")
    if (
        len(domain) > 253
        or len(labels) < 2
        or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
            for part in labels
        )
    ):
        raise OperationError("Invalid production domain")
    return values


def compose(*arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        "flowcredit",
        "--env-file",
        str(ENVIRONMENT),
        "-f",
        str(ROOT / "docker-compose.production.yml"),
        *arguments,
    ]


def run(arguments: list[str], *, stdout=None, stdin=None, timeout: int = 60) -> bytes:
    process_environment = os.environ.copy()
    # Compose must use the private file, not values inherited from a dev shell.
    for key in environment():
        process_environment.pop(key, None)
    try:
        result = subprocess.run(
            arguments,
            cwd=ROOT,
            env=process_environment,
            stdin=stdin if stdin is not None else subprocess.DEVNULL,
            stdout=stdout or subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise OperationError("Operation command unavailable or timed out") from error
    if result.returncode:
        # Upstream errors may contain credentials or transaction data. Keep them
        # out of journals and tickets; operators can inspect containers directly.
        raise OperationError(f"Operation command failed (exit {result.returncode})")
    return result.stdout or b""


@contextlib.contextmanager
def lock(name: str, *, shared: bool = False):
    private_directory(ROOT / "artifacts")
    path = ROOT / "artifacts" / name
    if path.is_symlink():
        raise OperationError("Operation lock must not be a symlink")
    with path.open("a") as descriptor:
        path.chmod(0o600)
        try:
            fcntl.flock(
                descriptor, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB
            )
        except BlockingIOError as error:
            raise OperationError(
                "Another deployment or operation is running"
            ) from error
        yield


def atomic_json(path: Path, data: dict) -> None:
    private_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def model_health(service: str) -> dict[str, str]:
    if service != "ml":
        raise OperationError("Production supports only the final ml service")
    raw = run(
        compose(
            "exec",
            "-T",
            service,
            "python",
            "-c",
            "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5).read().decode())",
        ),
        timeout=15,
    )
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise OperationError("Private scorer returned invalid health JSON") from error
    version = data.get("model_version")
    artifact = data.get("model_artifact_sha256")
    if (
        data.get("status") != "ok"
        or not isinstance(version, str)
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", version)
        or not isinstance(artifact, str)
        or not re.fullmatch(r"[a-f0-9]{64}", artifact)
    ):
        raise OperationError("Private scorer health identity is invalid")
    components = data.get("component_identity")
    try:
        encoded = json.dumps(
            components, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (TypeError, ValueError) as error:
        raise OperationError("Final scorer component identity is invalid") from error
    if (
        data.get("serving_mode") != "final_combined_model"
        or data.get("identity_scope") != "complete_local_model_assembly"
        or data.get("annual_interest_rate") != 0.24
        or data.get("human_review_required") is not True
        or not isinstance(components, dict)
        or not components
        or hashlib.sha256(encoded).hexdigest() != artifact
        or version != f"final-v1-{artifact[:16]}"
    ):
        raise OperationError("Private scorer is not the validated final assembly")
    return {
        "model_version": version,
        "model_artifact_sha256": artifact,
        "identity_scope": data["identity_scope"],
        "serving_mode": data["serving_mode"],
    }
