"""Train four declared real-revenue LightGBM candidates or predict frozen ones.

Training NPZ contains features (N, 21), targets (N,) and weights (N,). Prediction
JSON contains {cases: [{id, features: (12, 21), base_log: (12,), scale}]}, with no
future labels. This research runner never changes the product's default model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np

SCHEMA_VERSION = "real-revenue-lightgbm-benchmark-v1"
FEATURE_COUNT = 21
HORIZON = 12
RESIDUAL_BOUND = 3.0
MANIFEST_NAME = "real_lgb_manifest.json"
VARIANT_CONFIGS = {
    f"real_lgb_leaves{leaves}_rounds{rounds}": {
        "num_boost_round": rounds,
        "params": {
            "objective": "l1",
            "learning_rate": 0.04,
            "num_leaves": leaves,
            "min_data_in_leaf": 60,
            "lambda_l2": 1.0,
            "seed": 20261011,
            "num_threads": 1,
            "deterministic": True,
            "force_col_wise": True,
            "verbosity": -1,
        },
    }
    for leaves in (15, 31)
    for rounds in (200, 400)
}
SOURCE_LIMITATIONS = [
    "These four new research candidates are fitted only to the provided training NPZ, not synthetic borrower observations. The calling benchmark must document licensed source data, units, feature definitions, temporal splits and label lineage.",
    "Training targets are log(actual/history_scale + .05) minus log(damped/history_scale + .05). Prediction input contains history-derived features, baseline log forecasts and history scale only; no future outcome labels are accepted.",
    "The predeclared safety transform clips predicted residuals to [-3, 3], then computes max(exp(base_log + residual) - .05, 0) * scale. No additional financial or output clipping is applied.",
    "Only point revenue forecasts are available. No expense, capacity, repayment, default accuracy or calibrated interval coverage is established.",
    "Missing feature values may be NaN and remain LightGBM missing values. Unknown facts must not be replaced with fabricated labels.",
    "All four configurations are fixed before training. Development selection and terminal acceptance belong to the calling benchmark; these artifacts do not automatically replace the product default.",
]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_training(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != {"features", "targets", "weights"}:
            raise ValueError(
                "Training NPZ must contain only features, targets and weights."
            )
        features = np.asarray(archive["features"], dtype=float)
        targets = np.asarray(archive["targets"], dtype=float)
        weights = np.asarray(archive["weights"], dtype=float)
    if features.ndim != 2 or features.shape[1] != FEATURE_COUNT or not len(features):
        raise ValueError("Training features must have shape (N, 21), with N > 0.")
    if targets.shape != (len(features),) or weights.shape != targets.shape:
        raise ValueError("Training targets and weights must both have shape (N,).")
    if np.isinf(features).any() or not np.isfinite(targets).all():
        raise ValueError("Features cannot contain infinity and targets must be finite.")
    if not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError("Training weights must be finite and strictly positive.")
    return features, targets, weights


def train_variants(training_path: Path, artifact_dir: Path) -> dict:
    features, targets, weights = load_training(training_path)
    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        raise ValueError(
            "Training requires an empty artifact directory; use frozen prediction without --train for existing models."
        )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    identity = {
        "schema_version": SCHEMA_VERSION,
        "training_npz_sha256": file_sha256(training_path),
        "training_rows": len(features),
        "feature_count": FEATURE_COUNT,
        "training_missing_feature_values": int(np.isnan(features).sum()),
        "lightgbm_version": lgb.__version__,
        "residual_clip": [-RESIDUAL_BOUND, RESIDUAL_BOUND],
        "target_definition": "log(actual/history_scale+.05)-log(damped/history_scale+.05)",
        "artifact_hashes": {},
        "configs": VARIANT_CONFIGS,
        "actual_iterations": {},
    }
    for name, config in VARIANT_CONFIGS.items():
        dataset = lgb.Dataset(
            features, label=targets, weight=weights, free_raw_data=False
        )
        booster = lgb.train(
            config["params"], dataset, num_boost_round=config["num_boost_round"]
        )
        path = artifact_dir / f"{name}.txt"
        booster.save_model(str(path))
        identity["artifact_hashes"][name] = file_sha256(path)
        identity["actual_iterations"][name] = booster.current_iteration()
    (artifact_dir / MANIFEST_NAME).write_text(
        json.dumps(identity, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return identity


def load_variants(artifact_dir: Path) -> tuple[dict, dict[str, lgb.Booster]]:
    identity = json.loads((artifact_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    if (
        identity.get("schema_version") != SCHEMA_VERSION
        or identity.get("configs") != VARIANT_CONFIGS
        or identity.get("feature_count") != FEATURE_COUNT
        or identity.get("residual_clip") != [-RESIDUAL_BOUND, RESIDUAL_BOUND]
        or set(identity.get("artifact_hashes", {})) != set(VARIANT_CONFIGS)
    ):
        raise ValueError(
            "Artifact manifest differs from the declared four-configuration protocol."
        )
    models = {}
    for name, expected in identity["artifact_hashes"].items():
        path = artifact_dir / f"{name}.txt"
        if path.is_symlink() or file_sha256(path) != expected:
            raise ValueError(f"Frozen real-revenue artifact identity changed: {name}")
        models[name] = lgb.Booster(model_str=path.read_text(encoding="utf-8"))
    return identity, models


def validate_prediction_case(case: object) -> tuple[str, np.ndarray, np.ndarray, float]:
    if not isinstance(case, dict) or set(case) != {
        "id",
        "features",
        "base_log",
        "scale",
    }:
        raise ValueError(
            "Prediction cases must contain only id, features, base_log and scale; future labels are forbidden."
        )
    if not isinstance(case["id"], str) or not case["id"].strip():
        raise ValueError("Prediction case id must be a nonempty string.")
    features = np.asarray(case["features"], dtype=float)
    baseline = np.asarray(case["base_log"], dtype=float)
    if features.shape != (HORIZON, FEATURE_COUNT) or np.isinf(features).any():
        raise ValueError(
            "Prediction features must have shape (12, 21) without infinity; missing values may be NaN."
        )
    if baseline.shape != (HORIZON,) or not np.isfinite(baseline).all():
        raise ValueError("base_log must contain twelve finite history-derived values.")
    if type(case["scale"]) not in (int, float):
        raise ValueError("scale must be a finite positive number.")
    scale = float(case["scale"])
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be a finite positive number.")
    return case["id"], features, baseline, scale


def predict_case(booster: lgb.Booster, case: object) -> dict:
    started = time.perf_counter()
    identity = case.get("id") if isinstance(case, dict) else None
    result = {"id": identity if isinstance(identity, str) else None}
    try:
        _, features, baseline, scale = validate_prediction_case(case)
        residual = np.asarray(booster.predict(features, num_threads=1), dtype=float)
        if residual.shape != (HORIZON,) or not np.isfinite(residual).all():
            raise ValueError(
                "LightGBM residual predictions must be twelve finite values."
            )
        bounded = np.clip(residual, -RESIDUAL_BOUND, RESIDUAL_BOUND)
        with np.errstate(over="ignore", invalid="ignore"):
            prediction = np.maximum(np.exp(baseline + bounded) - 0.05, 0) * scale
        if not np.isfinite(prediction).all() or (prediction < 0).any():
            raise ValueError(
                "Rescaled revenue forecasts must be finite and nonnegative."
            )
        result.update(
            status="ok",
            predictions={"median": prediction.tolist()},
            clipped_residual_count=int(np.count_nonzero(bounded != residual)),
        )
    except (TypeError, ValueError, OverflowError, lgb.basic.LightGBMError) as error:
        result.update(
            status="error", reason={"code": "prediction_failed", "detail": str(error)}
        )
    result["inference_seconds"] = time.perf_counter() - started
    return result


def run(artifact_dir: Path, payload: object) -> dict:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"cases"}
        or not isinstance(payload["cases"], list)
    ):
        raise ValueError("Prediction input must contain only {cases: [...]}.")
    identity, models = load_variants(artifact_dir)
    return {
        "schema_version": SCHEMA_VERSION,
        "model_identity": identity,
        "source_limitations": SOURCE_LIMITATIONS,
        "variants": {
            name: {
                "model_identity": {
                    "training_npz_sha256": identity["training_npz_sha256"],
                    "artifact_sha256": identity["artifact_hashes"][name],
                    "config": identity["configs"][name],
                    "actual_iterations": identity["actual_iterations"][name],
                    "residual_clip": identity["residual_clip"],
                },
                "cases": [predict_case(booster, case) for case in payload["cases"]],
            }
            for name, booster in models.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        started = time.perf_counter()
        if args.train:
            train_variants(args.train, args.artifact_dir)
        result = run(args.artifact_dir, payload)
        result["elapsed_seconds"] = time.perf_counter() - started
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        lgb.basic.LightGBMError,
    ) as error:
        print(f"Real-revenue LightGBM benchmark failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
