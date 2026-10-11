#!/usr/bin/env python3
"""Publish commit and verified model identities; never publish environment data."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from common import ROOT, OperationError, checksum, fsync_directory, model_health, run


def publish(*, serving: bool = False) -> dict:
    commit = run(["git", "rev-parse", "HEAD"]).decode().strip()
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise OperationError("Deployment commit is invalid")
    if run(["git", "status", "--porcelain", "--untracked-files=no"]).strip():
        raise OperationError("Commit all tracked deployment changes before building")
    bundle = ROOT / "ml-service/final_model/artifacts/bundle.json"
    directory = ROOT / "artifacts/deployment"
    pending = directory / "release.pending.json"
    destination = directory / ("release.json" if serving else "release.pending.json")
    metadata = {
        "commit_sha": commit,
        "model_bundle_sha256": checksum(bundle),
        "status": "serving" if serving else "starting",
        "observed_at": datetime.now(UTC).isoformat(),
    }
    if serving:
        initial = json.loads(pending.read_text())
        if any(
            initial.get(key) != metadata[key]
            for key in ("commit_sha", "model_bundle_sha256")
        ):
            raise OperationError("Deployment sources changed during image creation")
        metadata["model"] = model_health("ml")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.chmod(0o755)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".release-")
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(metadata, output, sort_keys=True, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        Path(temporary).chmod(0o644)
        os.replace(temporary, destination)
        fsync_directory(destination.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serving", action="store_true")
    options = parser.parse_args()
    try:
        publish(serving=options.serving)
        return 0
    except (OperationError, OSError, ValueError):
        print(
            "Release identity publication failed; inspect committed deployment state."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
