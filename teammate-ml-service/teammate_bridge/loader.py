"""Verify every vendored byte before import; load the same snapshotted artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_candidate(vendor_root: Path | None = None, manifest_path: Path | None = None):
    vendor = vendor_root or ROOT / "vendor"
    manifest = json.loads((manifest_path or ROOT / "vendor-manifest.json").read_text())
    snapshots = {}
    for name, expected in manifest["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("Unsafe vendor manifest path")
        path = vendor / relative
        if path.is_symlink():
            raise RuntimeError(f"Vendor symlink forbidden: {name}")
        with path.open("rb") as source:
            data = source.read()
        if (
            len(data) != expected["bytes"]
            or hashlib.sha256(data).hexdigest() != expected["sha256"]
        ):
            raise RuntimeError(f"Frozen teammate artifact/source changed: {name}")
        snapshots[name] = data
    hashes = {
        name: hashlib.sha256(data).hexdigest()
        for name, data in snapshots.items()
        if name.startswith("models/artifacts/")
    }
    artifact_hash = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if artifact_hash != manifest["model_artifact_sha256"]:
        raise RuntimeError("Frozen teammate artifact manifest is inconsistent")

    # No external language-model calls are allowed from the candidate adapter,
    # regardless of inherited environment. The original numerical source is intact.
    os.environ["ML_ENABLE_LLM"] = "0"
    snapshot = tempfile.TemporaryDirectory(prefix="wiut-teammate-frozen-")
    snapshot_dir = Path(snapshot.name)
    for name, data in snapshots.items():
        destination = snapshot_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o400)
    sys.path.insert(0, str(snapshot_dir))
    from api.service import InputError, assess
    from models import llm
    from models.registry import load_bundle

    llm.ENABLE_LLM = False
    bundle = load_bundle(snapshot_dir / "models/artifacts")
    # Thread limits only affect inference execution; no learned values are changed.
    # LightGBM's reset_parameter() is a training API and is unsafe for a loaded
    # inference-only Booster. Supply the thread option to prediction instead.
    bundle.forecast.b_in.predict = partial(bundle.forecast.b_in.predict, num_threads=1)
    bundle.forecast.b_out.predict = partial(
        bundle.forecast.b_out.predict, num_threads=1
    )
    bridge_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "teammate_bridge").glob("*.py"))
    }
    bridge_hash = hashlib.sha256(
        json.dumps(bridge_hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = {**manifest, "bridge_source_sha256": bridge_hash}
    version = f"teammate-v1-{bundle.version}-{artifact_hash[:12]}-{bridge_hash[:8]}"
    return bundle, artifact_hash, version, manifest, snapshot, assess, InputError
