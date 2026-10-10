"""New-provider and unseen-engineering-cohort audit after candidate freeze.

The previous ABS/Canada final periods are consumed legacy regression benchmarks.
This module must never fit/select models or run before the next model freeze.
Synthetic engineering audit targets are explicitly not real repayment evidence.
"""

import hashlib
import inspect
import json
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np

from .forecasting import (
    FEATURE_NAMES,
    ForecastModel,
    MonthlyHistory,
    aggregate,
    feature_matrix,
    normalizer,
    seasonal_forecast,
)
from .generator import generate_business
from .public_data import calibration_digest
from .scoring import score_request

EXTERNAL_PROTOCOL_VERSION = "provider-audit-v2:engineering-positions-1000000-1000179"
PROTOCOL_VERSION = "engineering-audit-v5:positions-4000000-4000899"
ENGINEERING_POSITIONS = range(4_000_000, 4_000_900)
ENGINEERING_BOOTSTRAP_SEED = 20261012
BOOTSTRAP_REPLICATES = 2000
MAX_REVENUE_PROVIDER_REGRESSION_PCT = 10.0
MAX_NET_MACRO_REGRESSION = 1.02
MAX_NET_RAW_REGRESSION = 1.05
MAX_NET_COHORT_REGRESSION = 1.15
MIN_EFFECTIVE_REAL_WEIGHT = 0.50
ORIGINAL_TARGET_ABSOLUTE_TOLERANCE = 1e-9


def validate_original_target_pointwise(
    business_id: str,
    position: int,
    cohort: str,
    future_months: np.ndarray,
    native_targets: np.ndarray,
    original_case: dict,
) -> tuple[np.ndarray, float]:
    """Retain every consumed target while checking platform float roundoff."""
    if (
        business_id != original_case["business_id"]
        or position != original_case["position"]
        or cohort != original_case["cohort"]
        or np.asarray(future_months).tolist() != original_case["forecast_month_ids"]
    ):
        raise ValueError("Consumed original target identity/month alignment changed")
    native, original = (
        np.asarray(native_targets),
        np.asarray(original_case["future_net"]),
    )
    if (
        native.shape != (12,)
        or original.shape != (12,)
        or (np.any(~np.isfinite(native)) or np.any(~np.isfinite(original)))
    ):
        raise ValueError("Consumed target continuity requires twelve finite points")
    difference = float(np.max(np.abs(native - original)))
    if difference > ORIGINAL_TARGET_ABSOLUTE_TOLERANCE:
        raise ValueError(
            "Regenerated consumed targets differ from the original manifest "
            f"beyond {ORIGINAL_TARGET_ABSOLUTE_TOLERANCE}: {business_id}"
        )
    return original, difference


def synthetic_component_fingerprint(model: ForecastModel) -> dict:
    """Reference the unchanged synthetic comparator without generating cases."""
    from .train import fit_model

    # The original net training/validation selection precedes this marker.
    # Expense/transfer reselection below it must not change the comparator.
    prefix = inspect.getsource(fit_model).split("    # Revenue estimators", 1)[0]
    recipe = {
        "algorithm": "sha256-canonical-synthetic-net-recipe-v1",
        "estimator_parameters": model.estimator.get_params(),
        "blend_weight": model.blend_weight,
        "selected_candidate": model.selection["selected_candidate"],
        "feature_names": list(FEATURE_NAMES),
        "training_configuration": {
            key: model.selection[key]
            for key in (
                "seed",
                "train_ids",
                "validation_ids",
                "training_businesses",
                "validation_businesses",
                "training_origins",
                "training_examples",
                "training_origin_variants",
            )
        },
        "functions_sha256": {
            function.__qualname__: hashlib.sha256(
                inspect.getsource(function).encode()
            ).hexdigest()
            for function in (
                MonthlyHistory,
                aggregate,
                normalizer,
                seasonal_forecast,
                feature_matrix,
                ForecastModel.predict_candidates,
                ForecastModel.predict_synthetic,
            )
        },
        "net_fitting_and_selection_source_sha256": hashlib.sha256(
            prefix.encode()
        ).hexdigest(),
        "generator_and_calibration_source_sha256": {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in ("generator.py", "public_data.py")
        },
        "calibration_data_sha256": calibration_digest(),
        "dependencies_sha256": hashlib.sha256(
            Path(__file__).parents[1].joinpath("uv.lock").read_bytes()
        ).hexdigest(),
    }
    recipe_sha = hashlib.sha256(
        json.dumps(
            recipe, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    fitted = joblib.hash(model.estimator, hash_name="sha1")
    return {
        "recipe_sha256": recipe_sha,
        "fitted_estimator_sha1": fitted,
        "sha256": hashlib.sha256(f"{recipe_sha}:{fitted}".encode()).hexdigest(),
        "recipe": recipe,
        "scope": "Original synthetic net estimator and validation-selected blend, excluding expense/transfer projection. Recipe equality is portable; learned fingerprint equality is checked separately locally. Recorded from trusted v2 checkpoint without generating any audit case.",
    }


def revenue_component_fingerprint(model: ForecastModel) -> dict:
    """Identify the frozen revenue predictor without reading any audit cases.

    This deliberately excludes net blending, expense projection and scoring:
    those can change while the revenue component's original audit stays valid.
    Fitted parameters, revenue routing/features and source data must all match.
    """
    from .revenue_features import REVENUE_FEATURE_NAMES
    from .train import real_component_recipe_digest

    public = model.public_revenue_model
    parts = {
        "direct": public.estimator,
        "seasonal_residual": public.residual_estimator,
        "harmonic_residual": public.harmonic_estimator,
    }
    detail = {
        "algorithm": "sha256-canonical-json-with-joblib-sha1-fitted-estimators-v1",
        "selected_candidate": public.selected,
        "recipe_sha256": real_component_recipe_digest(),
        "fitted_estimators": {
            name: joblib.hash(estimator, hash_name="sha1")
            for name, estimator in parts.items()
        },
        "estimator_parameters": {
            name: estimator.get_params() for name, estimator in parts.items()
        },
        "feature_names": list(REVENUE_FEATURE_NAMES),
        "revenue_source_sha256": {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in ("public_revenue.py", "revenue_features.py")
        },
        "normalizer_source_sha256": hashlib.sha256(
            inspect.getsource(normalizer).encode()
        ).hexdigest(),
        "input_snapshot_sha256": {
            name: public.metadata[name]
            for name in (
                "data_sha256",
                "international_data_sha256",
                "external_data_sha256",
            )
        },
    }
    return {
        "sha256": hashlib.sha256(
            json.dumps(
                detail, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest(),
        **detail,
    }


def net_metrics(
    actual: list[np.ndarray], predictions: list[np.ndarray], scales: list[float]
) -> dict:
    if not actual or len(actual) != len(predictions) or len(actual) != len(scales):
        raise ValueError("Net metrics require nonempty aligned business windows")
    errors, normalized, absolute_actual, case_errors = [], [], [], []
    for targets, predicted, scale in zip(actual, predictions, scales, strict=True):
        targets, predicted = np.asarray(targets), np.asarray(predicted)
        if targets.shape != (12,) or predicted.shape != (12,):
            raise ValueError(
                "Net audit requires exactly twelve observed forecast months"
            )
        if (
            np.any(~np.isfinite(targets))
            or np.any(~np.isfinite(predicted))
            or not np.isfinite(scale)
            or scale <= 0
        ):
            raise ValueError(
                "Net metric inputs must be finite with positive history scale"
            )
        error = np.abs(targets - predicted)
        errors.extend(error.tolist())
        normalized.extend((error / scale).tolist())
        absolute_actual.extend(np.abs(targets).tolist())
        case_errors.append(float(np.mean(error) / scale))
    denominator = float(np.sum(absolute_actual))
    return {
        "businesses": len(actual),
        "observed_future_months": len(errors),
        "mae_index": float(np.mean(errors)),
        "macro_business_normalized_mae": float(np.mean(case_errors)),
        "absolute_net_wape_pct": float(np.sum(errors) / denominator * 100)
        if denominator > 0
        else None,
        "wape_excluded_zero_or_nearzero_months": 0,
    }


def business_improvement_interval(
    actual: list[np.ndarray],
    predictions: list[np.ndarray],
    baseline: list[np.ndarray],
    scales: list[float],
) -> dict:
    # Calling metrics first validates all shapes/values before bootstrap math.
    net_metrics(actual, predictions, scales)
    net_metrics(actual, baseline, scales)
    errors = np.asarray(
        [
            [
                float(np.mean(np.abs(target - forecast)) / scale),
                float(np.mean(np.abs(target - reference)) / scale),
            ]
            for target, forecast, reference, scale in zip(
                actual, predictions, baseline, scales, strict=True
            )
        ]
    )
    totals = np.sum(errors, axis=0)
    point = float((1 - totals[0] / totals[1]) * 100) if totals[1] > 0 else None
    interval = None
    usable = 0
    if len(errors) >= 2 and totals[1] > 0:
        indices = np.random.default_rng(ENGINEERING_BOOTSTRAP_SEED).integers(
            0, len(errors), size=(BOOTSTRAP_REPLICATES, len(errors))
        )
        resampled = np.sum(errors[indices], axis=1)
        positive = resampled[:, 1] > 0
        usable = int(np.count_nonzero(positive))
        if usable:
            changes = (1 - resampled[positive, 0] / resampled[positive, 1]) * 100
            interval = np.quantile(changes, [0.025, 0.975]).tolist()
    return {
        "macro_normalized_mae_improvement_pct": point,
        "business_bootstrap_95pct_interval": interval,
        "independent_generated_business_seeds": len(errors),
        "replicates": BOOTSTRAP_REPLICATES,
        "usable_replicates": usable,
        "seed": ENGINEERING_BOOTSTRAP_SEED,
        "scope": "Resample whole generated businesses, preserving twelve dependent future months. Synthetic stochastic seeds are independent; this interval does not describe real borrowers or default outcomes.",
    }


def engineering_acceptance(report: dict) -> dict:
    selected, baseline = report["selected"], report["fixed_synthetic_reference"]
    comparisons = {
        "macro_business_normalized_mae": selected["macro_business_normalized_mae"]
        <= baseline["macro_business_normalized_mae"] * MAX_NET_MACRO_REGRESSION,
        "pooled_mae_index": selected["mae_index"]
        <= baseline["mae_index"] * MAX_NET_RAW_REGRESSION,
        "cohort_regressions": all(
            values["selected"]["macro_business_normalized_mae"]
            <= values["fixed_synthetic_reference"]["macro_business_normalized_mae"]
            * MAX_NET_COHORT_REGRESSION
            for values in report["cohorts"].values()
        ),
        "majority_actual_real_component": report["effective_real_weight"]["mean"]
        >= MIN_EFFECTIVE_REAL_WEIGHT,
        "selected_uses_real_trained_estimator": report[
            "selected_uses_real_trained_estimator"
        ],
    }
    return {
        "status": "pass" if all(comparisons.values()) else "fail",
        "checks": comparisons,
        "rules_frozen_before_labels": True,
        "macro_error_maximum_ratio": MAX_NET_MACRO_REGRESSION,
        "raw_error_maximum_ratio": MAX_NET_RAW_REGRESSION,
        "cohort_macro_error_maximum_ratio": MAX_NET_COHORT_REGRESSION,
        "mean_effective_real_weight_minimum": MIN_EFFECTIVE_REAL_WEIGHT,
        "scope": "Finite-sample no-material-regression engineering tolerances, not a claimed accuracy gain or validated lending policy. Actual error improvement and uncertainty are reported separately.",
    }


def engineering_audit(
    model: ForecastModel, target_manifest: dict | None = None
) -> dict:
    # This is the only call site constructing the reserved positions. Keep it
    # out of training, formula tests and candidate selection.
    actual, predictions, reference, scales, weights = [], [], [], [], []
    cohorts: dict[str, list[int]] = defaultdict(list)
    histories: dict[str, list[int]] = defaultdict(list)
    request_ids, target_hash = [], hashlib.sha256()
    native_target_hash, maximum_target_difference = hashlib.sha256(), 0.0
    score_summaries = []
    for index, position in enumerate(ENGINEERING_POSITIONS):
        business = generate_business("test", position)
        request = business.request()
        history = aggregate(request)
        if business.business_id in set(model.selection["train_ids"]) | set(
            model.selection["validation_ids"]
        ):
            raise ValueError("Reserved engineering business overlaps fitting/selection")
        native_targets = business.future_net
        targets = native_targets
        if target_manifest is not None:
            targets, difference = validate_original_target_pointwise(
                business.business_id,
                position,
                business.cohort,
                business.months[business.cutoff : business.cutoff + 12],
                native_targets,
                target_manifest["cases"][index],
            )
            maximum_target_difference = max(maximum_target_difference, difference)
        actual.append(targets)
        result = score_request(request, model, "fresh-engineering-audit")
        predictions.append(np.asarray(result.seasonality.monthly_forecast_index))
        reference.append(model.predict_synthetic(history))
        scales.append(normalizer(history))
        effective_weight = getattr(model, "effective_real_weight", None)
        weights.append(
            float(effective_weight(history))
            if callable(effective_weight)
            else float(model.transfer_weight)
        )
        cohorts[business.cohort].append(index)
        length = len(history.inflow)
        histories["short_lt12" if length < 12 else "long_ge12"].append(index)
        request_ids.append(business.business_id)
        target_hash.update(business.business_id.encode())
        target_hash.update(targets.astype("<f8").tobytes())
        native_target_hash.update(business.business_id.encode())
        native_target_hash.update(native_targets.astype("<f8").tobytes())
        scheduled = sum(row.installment_index for row in result.adaptive_schedule)
        if not np.isclose(scheduled, result.recommended_loan.suggested_principal_index):
            raise ValueError("Repayment schedule does not sum to indexed principal")
        score_summaries.append(
            {
                "capacity_score": result.capacity_score,
                "principal_index": result.recommended_loan.suggested_principal_index,
                "confidence": result.confidence,
                "loan_months": len(result.adaptive_schedule),
                "flags": result.flags,
            }
        )

    def metrics(indices: list[int]) -> dict:
        rows = [actual[index] for index in indices]
        predicted = [predictions[index] for index in indices]
        baseline = [reference[index] for index in indices]
        history_scales = [scales[index] for index in indices]
        return {
            "selected": net_metrics(rows, predicted, history_scales),
            "fixed_synthetic_reference": net_metrics(rows, baseline, history_scales),
            "improvement": business_improvement_interval(
                rows, predicted, baseline, history_scales
            ),
        }

    report = {
        **metrics(list(range(len(actual)))),
        "protocol": {
            "positions_inclusive": [
                ENGINEERING_POSITIONS.start,
                ENGINEERING_POSITIONS.stop - 1,
            ],
            "businesses": len(actual),
            "generator_unchanged": True,
            "ids_sha256": hashlib.sha256("\n".join(request_ids).encode()).hexdigest(),
            "future_net_sha256": target_hash.hexdigest(),
            "target_truth": "New generated future inflow minus generated future outflow; never public expense/repayment/default labels",
        },
        "cohorts": {
            cohort: metrics(indices) for cohort, indices in sorted(cohorts.items())
        },
        "history_length": {
            label: metrics(indices) for label, indices in sorted(histories.items())
        },
        "effective_real_weight": {
            "mean": float(np.mean(weights)),
            "minimum": float(np.min(weights)),
            "maximum": float(np.max(weights)),
            "businesses_at_least_half": int(
                np.count_nonzero(np.asarray(weights) >= 0.5)
            ),
        },
        "selected_uses_real_trained_estimator": bool(
            model.public_revenue_model.metadata["selected_uses_trained_estimator"]
        ),
        "scoring_flow": {
            "valid_responses": len(score_summaries),
            "positive_principal_businesses": sum(
                row["principal_index"] > 0 for row in score_summaries
            ),
            "zero_principal_businesses": sum(
                row["principal_index"] == 0 for row in score_summaries
            ),
            "schedule_principal_sums_checked": True,
            "real_bank_capacity_validated": False,
        },
    }
    report["predetermined_acceptance"] = engineering_acceptance(report)
    if target_manifest is not None:
        report["original_target_continuity"] = {
            "status": "pass",
            "businesses_checked": len(actual),
            "individual_targets_checked": len(actual) * 12,
            "absolute_target_tolerance": ORIGINAL_TARGET_ABSOLUTE_TOLERANCE,
            "relative_target_tolerance": 0,
            "maximum_absolute_native_target_difference": maximum_target_difference,
            "original_future_net_sha256": target_hash.hexdigest(),
            "native_regenerated_future_net_sha256": native_target_hash.hexdigest(),
            "raw_float64_target_hash_exact_match": target_hash.hexdigest()
            == native_target_hash.hexdigest(),
            "metrics_use": "Frozen original Mac targets, after every regenerated point passed declared continuity; native regenerated hash is reported separately",
        }
    return report


def external_acceptance(
    audit: dict, expected_providers: set[str] | None = None
) -> dict:
    improvement = audit["overall"]["improvement"][
        "macro_case_normalized_mae_improvement_pct"
    ]
    by_provider = {
        provider: values["improvement"]["macro_case_normalized_mae_improvement_pct"]
        for provider, values in audit["providers"].items()
    }
    missing = sorted((expected_providers or set()) - set(by_provider))
    passed = (
        improvement is not None
        and improvement > 0
        and not missing
        and all(
            change is not None and change >= -MAX_REVENUE_PROVIDER_REGRESSION_PCT
            for change in by_provider.values()
        )
    )
    return {
        "status": "pass" if passed else "fail",
        "overall_normalized_mae_improvement_must_exceed_pct": 0,
        "maximum_provider_normalized_mae_regression_pct": 10,
        "measured_overall_improvement_pct": improvement,
        "measured_provider_improvements_pct": by_provider,
        "missing_expected_providers": missing,
        "rules_frozen_before_labels": True,
        "scope": "Engineering forecast acceptance on new-provider actual revenue; not bank repayment/default validation",
    }
