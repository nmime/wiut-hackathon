"""Bounded, real-revenue LightGBM experiment with enriched history-only inputs.

Feature construction imports only NumPy; training and frozen inference lazily
import LightGBM. This module never reads holdout labels or changes serving.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

SCHEMA_VERSION = "improved-real-revenue-lightgbm-v1"
HORIZON = 12
ANCHORS = ("damped_seasonal", "flat_harmonic")
OBJECTIVES = ("log_residual", "linear_residual")
LOG_RESIDUAL_BOUND = 3.0
LINEAR_RESIDUAL_BOUND = 5.0
MANIFEST_NAME = "improved_revenue_manifest.json"
BASE_FEATURE_NAMES = (
    *(f"target_prior_year_offset_{offset}" for offset in range(-3, 4)),
    "target_two_years_ago",
    "target_three_years_ago",
    "mean_3",
    "mean_6",
    "std_12",
    "annual_log_growth",
    "horizon",
    "history_length",
    "recent_level_change",
    "seasonal_naive",
    "damped_seasonal",
    "robust_harmonic",
    "linear_harmonic",
    "flat_harmonic",
)
EXTRA_FEATURE_NAMES = (
    "recent_lag_1",
    "recent_lag_2",
    "recent_lag_3",
    "recent_lag_6",
    "recent_lag_12",
    "median_3",
    "median_6",
    "median_12",
    "annual_log_slope_3",
    "annual_log_slope_6",
    "annual_log_slope_12",
    "annual_log_slope_24",
    "log_recent_three_to_previous_three",
    "log_last_to_median_three",
    "std_3",
    "std_6",
    "std_log_differences_12",
    "zero_share_12",
    "autocorrelation_12",
    "median_log_year_growth",
    "log_recent_three_year_growth",
    "target_same_month_support",
    "target_same_month_last",
    "target_same_month_median",
    "target_same_month_iqr",
    "target_same_month_log_growth",
    "baseline_range",
    "log_damped_to_flat",
    "log_linear_to_robust",
    "local_damped_drift",
    "seasonal_to_recent_level",
    "has_full_year",
    "has_two_years",
    "log_recent_six_to_history_median",
)
FEATURE_NAMES = BASE_FEATURE_NAMES + EXTRA_FEATURE_NAMES
FEATURE_COUNT = len(FEATURE_NAMES)
BASELINES = (
    "seasonal_naive",
    "damped_seasonal",
    "robust_harmonic",
    "linear_harmonic",
    "flat_harmonic",
)
VARIANT_CONFIGS = {
    f"improved_lgb_{anchor}_{objective}_leaves{leaves}": {
        "anchor": anchor,
        "objective_transform": objective,
        "num_boost_round": 400,
        "params": {
            "objective": "l1",
            "learning_rate": 0.04,
            "num_leaves": leaves,
            "max_depth": 6,
            "min_data_in_leaf": 60,
            "lambda_l2": 5.0,
            "seed": 20261011,
            "num_threads": 1,
            "deterministic": True,
            "force_col_wise": True,
            "verbosity": -1,
        },
    }
    for anchor in ANCHORS
    for objective in OBJECTIVES
    for leaves in (15, 31)
}
SOURCE_LIMITATIONS = [
    "This experiment predicts real aggregate revenue only. It supplies no borrower expense, capacity, repayment, default or calibrated interval claim.",
    "The calling experiment owns licensed source provenance, geography/temporal isolation and provider-balanced weights. Only explicitly authorized training labels may enter the training NPZ.",
    "History features are scale invariant and depend on observed revenues and target-relative seasonal support. There are no country, provider, absolute calendar-phase, expense, channel or counterparty inputs.",
    "History views {3,6,12,full} must split each origin/provider training weight across unique available lengths. Repeated views do not supply independent labels or extra target importance.",
    "Missing seasonal observations remain missing values. Short-history forecasts do not establish that unseen seasonal peaks can be recovered from three months of observations.",
    "The fixed eight-config grid learns L1 log or normalized-linear residuals to damped-seasonal or flat-harmonic anchors. Residual limits ±3 and ±5 respectively are fixed experimental choices, not holdout-tuned safeguards.",
    "Development selection, incumbent mixtures, eligibility and fresh holdout acceptance are external to this trainer. Frozen prediction --variant evaluates only the selected model; serving is unchanged.",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def protocol() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "feature_count": FEATURE_COUNT,
        "anchor_columns": list(ANCHORS),
        "configs": VARIANT_CONFIGS,
        "log_residual_bound": LOG_RESIDUAL_BOUND,
        "linear_residual_bound": LINEAR_RESIDUAL_BOUND,
        "history_views": [3, 6, 12, "full"],
        "scale": "positive_mean_of_latest_up_to_12_observed_revenues",
    }


def source_identity() -> dict:
    root = Path(__file__).resolve().parents[2]
    dependencies = {
        name: sha256_bytes((root / "ml-service/capacity_ml" / name).read_bytes())
        for name in ("revenue_features.py", "forecasting.py")
    }
    return {
        "trainer_source_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "base_feature_source_hashes": dependencies,
        "protocol_sha256": sha256_bytes(
            json.dumps(protocol(), sort_keys=True, separators=(",", ":")).encode()
        ),
    }


def _history(months, inflow, forecast_start) -> tuple[np.ndarray, np.ndarray, float]:
    indices = np.asarray(months)
    revenue = np.asarray(inflow, dtype=float)
    if (
        indices.ndim != 1
        or revenue.shape != indices.shape
        or not 3 <= len(indices) <= 600
    ):
        raise ValueError(
            "Observed history must contain 3–600 aligned monthly revenues."
        )
    if indices.dtype.kind not in "iu" or any(np.diff(indices) != 1):
        raise ValueError(
            "History must use sorted, unique, continuous integer month IDs."
        )
    if (
        isinstance(forecast_start, bool)
        or not isinstance(forecast_start, (int, np.integer))
        or int(forecast_start) != int(indices[-1]) + 1
    ):
        raise ValueError("Forecast start must immediately follow observed history.")
    if not np.isfinite(revenue).all() or (revenue < 0).any():
        raise ValueError("Observed revenue must be finite and nonnegative.")
    scale = float(np.mean(revenue[-12:]))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError(
            "Latest up to twelve observed months need a finite positive mean."
        )
    return indices.astype(int), revenue / scale, scale


def enriched_features(
    months, inflow, forecast_start, base_features, baselines
) -> tuple[np.ndarray, float]:
    """Append observed-only features to the frozen 21-feature revenue recipe."""
    indices, values, scale = _history(months, inflow, forecast_start)
    original = np.asarray(base_features, dtype=float)
    if original.shape != (HORIZON, len(BASE_FEATURE_NAMES)) or np.isinf(original).any():
        raise ValueError("Base features must be (12, 21), without infinity.")
    if not isinstance(baselines, dict) or set(baselines) != set(BASELINES):
        raise ValueError("All five frozen history-derived baselines must be supplied.")
    normalized_baselines = {}
    for name, data in baselines.items():
        vector = np.asarray(data, dtype=float)
        if (
            vector.shape != (HORIZON,)
            or not np.isfinite(vector).all()
            or (vector < 0).any()
        ):
            raise ValueError(
                "Baseline forecasts must have twelve finite nonnegative values."
            )
        normalized_baselines[name] = vector / scale
    logs = np.log(values + 0.05)
    n = len(values)

    def window_stat(count, function):
        return float(function(values[-count:])) if n >= count else np.nan

    def slope(count):
        if n < count:
            return np.nan
        return float(
            np.clip(np.polyfit(np.arange(count), logs[-count:], 1)[0] * 12, -0.7, 0.7)
        )

    def log_ratio(a, b):
        return float(np.log((a + 0.05) / (b + 0.05)))

    median_three = float(np.median(values[-3:]))
    annual_drift = slope(min(n, 12))
    corr = np.nan
    yearly_growth = np.nan
    if n >= 24:
        previous, recent = values[-24:-12], values[-12:]
        denominator = float(np.std(previous) * np.std(recent))
        corr = (
            float(
                np.mean((previous - previous.mean()) * (recent - recent.mean()))
                / denominator
            )
            if denominator > 0
            else 0.0
        )
        yearly_growth = float(np.median(np.log((recent + 0.05) / (previous + 0.05))))
    constants = [
        *(float(values[-lag]) if n >= lag else np.nan for lag in (1, 2, 3, 6, 12)),
        *(window_stat(count, np.median) for count in (3, 6, 12)),
        *(slope(count) for count in (3, 6, 12, 24)),
        log_ratio(np.mean(values[-3:]), np.mean(values[-6:-3])) if n >= 6 else np.nan,
        log_ratio(values[-1], median_three),
        window_stat(3, np.std),
        window_stat(6, np.std),
        float(np.std(np.diff(logs[-12:]))),
        float(np.mean(values[-12:] == 0)),
        corr,
        yearly_growth,
        log_ratio(np.mean(values[-3:]), np.mean(values[-15:-12]))
        if n >= 15
        else np.nan,
    ]
    rows = []
    for offset in range(HORIZON):
        target = int(forecast_start) + offset
        matches = values[indices % 12 == target % 12]
        support = len(matches)
        target_values = [
            float(support),
            float(matches[-1]) if support else np.nan,
            float(np.median(matches)) if support else np.nan,
            float(np.quantile(matches, 0.75) - np.quantile(matches, 0.25))
            if support
            else np.nan,
            log_ratio(matches[-1], matches[-2]) if support >= 2 else np.nan,
        ]
        current = [normalized_baselines[name][offset] for name in BASELINES]
        drift = median_three * np.exp(
            annual_drift / 12 * sum(0.85**horizon for horizon in range(1, offset + 2))
        )
        remaining = [
            float(max(current) - min(current)),
            log_ratio(
                normalized_baselines["damped_seasonal"][offset],
                normalized_baselines["flat_harmonic"][offset],
            ),
            log_ratio(
                normalized_baselines["linear_harmonic"][offset],
                normalized_baselines["robust_harmonic"][offset],
            ),
            float(drift),
            normalized_baselines["seasonal_naive"][offset] - median_three,
            float(n >= 12),
            float(n >= 24),
            log_ratio(np.mean(values[-6:]), np.median(values)),
        ]
        rows.append(constants + target_values + remaining)
    features = np.hstack([original, np.asarray(rows, dtype=float)])
    if features.shape != (HORIZON, FEATURE_COUNT) or np.isinf(features).any():
        raise ValueError(
            "Enriched features do not match the frozen finite-or-missing schema."
        )
    return features, scale


def make_prediction_case(
    identity, months, inflow, forecast_start, base_features, baselines
) -> dict:
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("Case id must be a nonempty string.")
    features, scale = enriched_features(
        months, inflow, forecast_start, base_features, baselines
    )
    return {
        "id": identity,
        "features": [
            [None if np.isnan(value) else float(value) for value in row]
            for row in features
        ],
        "normalized_baselines": {
            name: (np.asarray(baselines[name], dtype=float) / scale).tolist()
            for name in ANCHORS
        },
        "scale": scale,
    }


def load_training(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != {
            "features",
            "normalized_targets",
            "normalized_baselines",
            "weights",
        }:
            raise ValueError(
                "Training NPZ needs only features, normalized_targets, normalized_baselines and weights."
            )
        features = np.asarray(archive["features"], dtype=float)
        targets = np.asarray(archive["normalized_targets"], dtype=float)
        baselines = np.asarray(archive["normalized_baselines"], dtype=float)
        weights = np.asarray(archive["weights"], dtype=float)
    if (
        features.ndim != 2
        or features.shape[1] != FEATURE_COUNT
        or len(features) == 0
        or np.isinf(features).any()
    ):
        raise ValueError(
            f"Training features need shape (N, {FEATURE_COUNT}), N > 0, with finite or missing values."
        )
    if (
        targets.shape != (len(features),)
        or not np.isfinite(targets).all()
        or (targets < 0).any()
    ):
        raise ValueError(
            "Normalized training revenue targets must be finite nonnegative (N,)."
        )
    if (
        baselines.shape != (len(features), len(ANCHORS))
        or not np.isfinite(baselines).all()
        or (baselines < 0).any()
    ):
        raise ValueError(
            "Normalized training baselines must be finite nonnegative (N, 2)."
        )
    if (
        weights.shape != targets.shape
        or not np.isfinite(weights).all()
        or (weights <= 0).any()
    ):
        raise ValueError("Training weights must be finite strictly positive (N,).")
    return features, targets, baselines, weights


def train(
    training_path: Path, artifact_dir: Path, data_manifest: Path | None = None
) -> dict:
    import lightgbm as lgb

    features, targets, baselines, weights = load_training(training_path)
    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        raise ValueError(
            "Training requires an empty artifact directory; existing models are frozen."
        )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    identity = {
        "protocol": protocol(),
        "source_identity": source_identity(),
        "training_npz_sha256": sha256_bytes(training_path.read_bytes()),
        "training_data_manifest_sha256": sha256_bytes(data_manifest.read_bytes())
        if data_manifest
        else None,
        "training_rows": len(features),
        "training_missing_feature_values": int(np.isnan(features).sum()),
        "lightgbm_version": lgb.__version__,
        "artifact_hashes": {},
        "actual_iterations": {},
    }
    for name, config in VARIANT_CONFIGS.items():
        base = baselines[:, ANCHORS.index(config["anchor"])]
        residual = (
            np.log(targets + 0.05) - np.log(base + 0.05)
            if config["objective_transform"] == "log_residual"
            else targets - base
        )
        dataset = lgb.Dataset(
            features,
            label=residual,
            weight=weights,
            feature_name=list(FEATURE_NAMES),
            free_raw_data=False,
        )
        booster = lgb.train(
            config["params"], dataset, num_boost_round=config["num_boost_round"]
        )
        model_path = artifact_dir / f"{name}.txt"
        booster.save_model(str(model_path))
        identity["artifact_hashes"][name] = sha256_bytes(model_path.read_bytes())
        identity["actual_iterations"][name] = booster.current_iteration()
    (artifact_dir / MANIFEST_NAME).write_text(
        json.dumps(identity, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return identity


def load_models(artifact_dir: Path, variant: str | None = None) -> tuple[dict, dict]:
    import lightgbm as lgb

    if variant is not None and variant not in VARIANT_CONFIGS:
        raise ValueError("Unknown predeclared model variant.")
    identity = json.loads((artifact_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    if (
        identity.get("protocol") != protocol()
        or identity.get("source_identity") != source_identity()
        or set(identity.get("artifact_hashes", {})) != set(VARIANT_CONFIGS)
    ):
        raise ValueError("Frozen protocol, feature source or model manifest changed.")
    models = {}
    for name, expected in identity["artifact_hashes"].items():
        path = artifact_dir / f"{name}.txt"
        if path.is_symlink():
            raise ValueError(f"Frozen model cannot be a symlink: {name}")
        data = path.read_bytes()
        if sha256_bytes(data) != expected:
            raise ValueError(f"Frozen model bytes changed: {name}")
        if variant is None or variant == name:
            models[name] = lgb.Booster(model_str=data.decode("utf-8"))
    return identity, models


def predict_case(booster, config: dict, case: object) -> dict:
    started = time.perf_counter()
    identity = case.get("id") if isinstance(case, dict) else None
    result = {"id": identity if isinstance(identity, str) else None}
    try:
        if not isinstance(case, dict) or set(case) != {
            "id",
            "features",
            "normalized_baselines",
            "scale",
        }:
            raise ValueError(
                "Prediction cases allow only id, features, normalized_baselines and scale; future labels are forbidden."
            )
        if not isinstance(case["id"], str) or not case["id"].strip():
            raise ValueError("Case id must be a nonempty string.")
        features = np.asarray(case["features"], dtype=float)
        if features.shape != (HORIZON, FEATURE_COUNT) or np.isinf(features).any():
            raise ValueError(
                "Prediction features do not match the frozen finite-or-missing schema."
            )
        baselines = case["normalized_baselines"]
        if not isinstance(baselines, dict) or set(baselines) != set(ANCHORS):
            raise ValueError(
                "Prediction needs exactly both predeclared normalized anchors."
            )
        for values in baselines.values():
            vector = np.asarray(values, dtype=float)
            if (
                vector.shape != (HORIZON,)
                or not np.isfinite(vector).all()
                or (vector < 0).any()
            ):
                raise ValueError(
                    "Prediction anchors must be finite nonnegative twelve-month values."
                )
        if (
            type(case["scale"]) not in (int, float)
            or not math.isfinite(case["scale"])
            or case["scale"] <= 0
        ):
            raise ValueError("Prediction scale must be finite and positive.")
        base = np.asarray(baselines[config["anchor"]], dtype=float)
        residual = np.asarray(booster.predict(features, num_threads=1), dtype=float)
        if residual.shape != (HORIZON,) or not np.isfinite(residual).all():
            raise ValueError("Model residuals must be twelve finite values.")
        bound = (
            LOG_RESIDUAL_BOUND
            if config["objective_transform"] == "log_residual"
            else LINEAR_RESIDUAL_BOUND
        )
        bounded = np.clip(residual, -bound, bound)
        with np.errstate(over="ignore", invalid="ignore"):
            normalized = (
                np.maximum(np.exp(np.log(base + 0.05) + bounded) - 0.05, 0)
                if config["objective_transform"] == "log_residual"
                else np.maximum(base + bounded, 0)
            )
            prediction = normalized * case["scale"]
        if not np.isfinite(prediction).all() or (prediction < 0).any():
            raise ValueError("Reconstructed revenue must be finite and nonnegative.")
        result.update(
            status="ok",
            predictions={"median": prediction.tolist()},
            clipped_residual_count=int(np.count_nonzero(bounded != residual)),
        )
    except Exception as error:
        result.update(
            status="error", reason={"code": "prediction_failed", "detail": str(error)}
        )
    result["inference_seconds"] = time.perf_counter() - started
    return result


def run(artifact_dir: Path, payload: object, variant: str | None = None) -> dict:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"cases"}
        or not isinstance(payload["cases"], list)
    ):
        raise ValueError("Prediction input must contain only {cases: [...]}.")
    identity, models = load_models(artifact_dir, variant)
    return {
        "schema_version": SCHEMA_VERSION,
        "model_identity": identity,
        "source_limitations": SOURCE_LIMITATIONS,
        "selected_variant_only": variant,
        "variants": {
            name: {
                "model_identity": {
                    "training_npz_sha256": identity["training_npz_sha256"],
                    "artifact_sha256": identity["artifact_hashes"][name],
                    "config": VARIANT_CONFIGS[name],
                    "source_identity": identity["source_identity"],
                },
                "cases": [
                    predict_case(booster, VARIANT_CONFIGS[name], case)
                    for case in payload["cases"]
                ],
            }
            for name, booster in models.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path)
    parser.add_argument("--data-manifest", type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--variant", choices=tuple(VARIANT_CONFIGS))
    args = parser.parse_args(argv)
    try:
        if args.variant and args.train:
            raise ValueError(
                "--variant is prediction-only; development training fits the fixed eight models."
            )
        if args.data_manifest and not args.train:
            raise ValueError(
                "--data-manifest applies only when creating training artifacts."
            )
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        started = time.perf_counter()
        if args.train:
            train(args.train, args.artifact_dir, args.data_manifest)
        result = run(args.artifact_dir, payload, args.variant)
        result["elapsed_seconds"] = time.perf_counter() - started
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(f"Improved revenue experiment failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
