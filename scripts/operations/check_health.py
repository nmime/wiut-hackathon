#!/usr/bin/env python3
"""Local status/journal checks; no customer data or outbound notifications."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backup import OWNED_ARCHIVE
from common import (
    BACKUPS,
    MODEL_SERVICES,
    ROOT,
    STATE,
    OperationError,
    atomic_json,
    compose,
    environment,
    lock,
    model_health,
    private_directory,
    run,
)


def http_status(url: str, *, host: str | None = None) -> tuple[int, bytes]:
    request = Request(url, headers={"Host": host} if host else {})
    try:
        with urlopen(request, timeout=8) as response:
            data = response.read(65537)
            if len(data) > 65536:
                raise OperationError("Health response exceeded bound")
            return response.status, data
    except HTTPError as error:
        return error.code, b""


def database_health(url: str, *, host: str | None = None) -> bool:
    status, body = http_status(url, host=host)
    data = json.loads(body) if status == 200 else {}
    return (
        status == 200
        and data.get("status") == "ok"
        and data.get("database") == "connected"
        and data.get("ml_configured") is True
    )


def certificate_hostname_matches(certificate: str, domain: str) -> bool:
    # OpenSSL can exit successfully while printing a hostname mismatch. Require
    # its exact positive result rather than treating exit status as sufficient.
    result = run(
        ["openssl", "x509", "-in", certificate, "-noout", "-checkhost", domain]
    )
    return result.strip() == f"Hostname {domain} does match certificate".encode()


def observe(*, accept_models: bool = False) -> dict:
    values = environment()
    domain = values["DOMAIN"]
    selected = MODEL_SERVICES.get(
        values.get("ML_SERVICE_URL", "http://ml:8000").rstrip("/")
    )
    checks: dict[str, str] = {}
    models = {}

    def check(name, operation):
        try:
            checks[name] = "ok" if operation() else "failed"
        except (
            OperationError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ):
            checks[name] = "failed"

    check(
        "local_api_database",
        lambda: database_health("http://127.0.0.1:18080/api/health", host=domain),
    )
    check(
        "public_https_database", lambda: database_health(f"https://{domain}/api/health")
    )
    check(
        "anonymous_businesses_protected",
        lambda: http_status(f"https://{domain}/api/businesses")[0] == 401,
    )
    checks["selected_scorer_supported"] = "ok" if selected else "failed"
    for service in ("db", "api", "web", "ml", "teammate-ml"):
        try:
            identifiers = (
                run(compose("ps", "--all", "--quiet", service)).decode().split()
            )
            if not identifiers and service == "teammate-ml" and selected != service:
                continue
            if len(identifiers) != 1:
                raise OperationError("Expected one container")
            state = (
                run(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}",
                        identifiers[0],
                    ]
                )
                .decode()
                .strip()
            )
            checks[f"container_{service}"] = (
                "ok" if state == "running healthy" else "failed"
            )
            if service in ("ml", "teammate-ml") and state == "running healthy":
                models[service] = model_health(service)
                checks[f"scorer_{service}_identity_valid"] = "ok"
        except (
            OperationError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ):
            checks[f"container_{service}"] = "failed"
    if selected and selected not in models:
        checks["selected_scorer_available"] = "failed"
    baseline_path = STATE / "model-baseline.json"
    if accept_models:
        checks["scorer_baseline"] = "ok" if models else "failed"
    else:
        try:
            baseline = json.loads(baseline_path.read_text())
            checks["scorer_baseline"] = (
                "ok" if baseline.get("models") == models else "failed"
            )
        except (OSError, ValueError):
            checks["scorer_baseline"] = "failed"
    usage = shutil.disk_usage(ROOT)
    checks["disk_headroom"] = (
        "ok"
        if usage.free >= 5 * 1024**3 and usage.used / usage.total < 0.9
        else "failed"
    )
    certificate = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
    check(
        "origin_certificate_14_days",
        lambda: (
            run(
                [
                    "openssl",
                    "x509",
                    "-in",
                    certificate,
                    "-noout",
                    "-checkend",
                    str(14 * 86400),
                ]
            )
            is not None
        ),
    )
    check(
        "origin_certificate_hostname",
        lambda: certificate_hostname_matches(certificate, domain),
    )
    check(
        "certificate_renewal_timer",
        lambda: run(["systemctl", "is-active", "certbot.timer"]).strip() == b"active",
    )
    try:
        archives = [
            path
            for path in BACKUPS.iterdir()
            if OWNED_ARCHIVE.fullmatch(path.name)
            and path.is_file()
            and not path.is_symlink()
        ]
        latest = max(archives, key=lambda path: path.stat().st_mtime)
        status = json.loads((STATE / "backup-status.json").read_text())
        checks["backup_recent_26_hours"] = (
            "ok"
            if time.time() - latest.stat().st_mtime < 26 * 3600
            and status.get("status") == "ok"
            else "failed"
        )
    except (OSError, ValueError):
        checks["backup_recent_26_hours"] = "failed"
    status = "ok" if all(value == "ok" for value in checks.values()) else "failed"
    if accept_models and status == "ok":
        atomic_json(
            baseline_path,
            {"accepted_at": datetime.now(UTC).isoformat(), "models": models},
        )
    return {
        "status": status,
        "checks": checks,
        "models": models,
        "selected_scorer": selected,
        "observed_at": datetime.now(UTC).isoformat(),
    }


def publish(status: dict) -> None:
    path = STATE / "health-status.json"
    try:
        previous = json.loads(path.read_text())
    except (OSError, ValueError):
        previous = {}
    # Only state/model changes generate our journal output. Timestamps refresh in
    # the private status file, and failures still return nonzero to systemd.
    comparison = lambda data: {
        key: value for key, value in data.items() if key != "observed_at"
    }
    atomic_json(path, status)
    if comparison(previous) != comparison(status):
        print(json.dumps(comparison(status), sort_keys=True))


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--accept-models",
        action="store_true",
        help="Explicitly pin current healthy scorer identities after qualification",
    )
    options = parser.parse_args()
    private_directory(STATE)
    try:
        with lock("operations-health.lock"):
            try:
                with lock("deploy.lock", shared=True):
                    status = observe(accept_models=options.accept_models)
            except OperationError as error:
                if str(error) != "Another deployment or operation is running":
                    raise
                status = {
                    "status": "maintenance",
                    "observed_at": datetime.now(UTC).isoformat(),
                }
            publish(status)
            return 1 if status["status"] == "failed" else 0
    except (OperationError, OSError, ValueError):
        publish(
            {
                "status": "failed",
                "checks": {"operations_configuration": "failed"},
                "observed_at": datetime.now(UTC).isoformat(),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
