"""Train real revenue and synthetic expenses; select transfer on validation only."""

import argparse
import hashlib
import inspect
import json
import math
import os
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .forecasting import (
    FEATURE_NAMES,
    TRANSFER_WEIGHTS,
    ForecastModel,
    MonthlyHistory,
    aggregate,
    expense_projection_policies,
    feature_matrix,
    normalizer,
    observed_expense_candidates,
    pipeline_source_digest,
    seasonal_forecast,
    transfer_policies,
    transfer_policy_weight,
)
from .generator import SEED, TRAIN_COUNT, VALIDATION_COUNT, generate_split
from .public_data import calibration_digest
from .public_revenue import TRAINED_CANDIDATES, fit_public_revenue_model
from .schemas import ScoreRequest

# The real component was selected on development validation before its external
# audit. Net-policy reselection must not alter the component that audit measured.
FROZEN_REAL_REVENUE_CANDIDATE = "adaptive_revenue_10"
FROZEN_REAL_RECIPE_SHA256 = (
    "9c3d04c3dac884a8e1c05f0c3a980650aaf2f8e73fdbaab8086cefa956877f2f"
)
DEVELOPMENT_COHORT_ERROR_RATIO = 1.10


def effective_weight_summary(weights: list[float]) -> dict:
    """Use accurate summation so a mathematical 55% share remains eligible."""
    return {
        "mean": math.fsum(weights) / len(weights),
        "min": min(weights),
        "max": max(weights),
        "requests": len(weights),
        "by_weight": {
            str(weight): weights.count(weight) for weight in sorted(set(weights))
        },
    }


def real_component_recipe_digest() -> str:
    """Platform-independent recipe; exact fitted continuity is checked locally."""
    from .external_data import external_data_digest
    from .international_data import international_data_digest
    from .revenue_data import revenue_data_digest

    root = Path(__file__).parent
    digest = hashlib.sha256()
    for name in (
        "public_revenue.py",
        "revenue_features.py",
        "revenue_data.py",
        "international_data.py",
        "external_data.py",
    ):
        digest.update(name.encode())
        digest.update(root.joinpath(name).read_bytes())
    digest.update(root.parent.joinpath("uv.lock").read_bytes())
    for function in (MonthlyHistory, normalizer, seasonal_forecast):
        digest.update(inspect.getsource(function).encode())
    for data_digest in (
        revenue_data_digest(),
        international_data_digest(),
        external_data_digest(),
    ):
        digest.update(data_digest.encode())
    digest.update(FROZEN_REAL_REVENUE_CANDIDATE.encode())
    return digest.hexdigest()


def fit_model() -> ForecastModel:
    train = generate_split("train")
    validation = generate_split("validation")
    train_ids = {business.business_id for business in train}
    validation_ids = {business.business_id for business in validation}
    assert not train_ids & validation_ids
    x_parts, y_parts, expense_parts = [], [], []
    origins = 0
    for business in train:
        # Rolling origins use only transactions before each cutoff. Targets are
        # later actual monthly events. Never use validation or test businesses.
        cutoffs = sorted(set([business.cutoff] + list(range(12, business.cutoff, 6))))
        for cutoff in cutoffs:
            complete_request = business.request(cutoff)
            partial_payload = complete_request.model_dump()
            partial_payload["as_of_date"] = complete_request.as_of_date[:8] + "20"
            partial_payload["transactions"] = [
                row
                for row in partial_payload["transactions"]
                if row["ts"][:10] <= partial_payload["as_of_date"]
            ]
            for request in (
                complete_request,
                ScoreRequest.model_validate(partial_payload),
            ):
                history = aggregate(request)
                x_parts.append(feature_matrix(history))
                y_parts.append(
                    (business.inflow - business.outflow)[cutoff : cutoff + 12]
                    / normalizer(history)
                )
                expense_parts.append(
                    business.outflow[cutoff : cutoff + 12] / normalizer(history)
                )
                origins += 1
    estimator = HistGradientBoostingRegressor(
        loss="absolute_error",
        learning_rate=0.08,
        max_iter=160,
        max_leaf_nodes=15,
        l2_regularization=2.0,
        min_samples_leaf=25,
        early_stopping=False,
        random_state=SEED,
    )
    with threadpool_limits(limits=1):
        x = np.vstack(x_parts)
        estimator.fit(x, np.concatenate(y_parts))
        expense_estimator = HistGradientBoostingRegressor(**estimator.get_params())
        expense_estimator.fit(x, np.concatenate(expense_parts))
    model = ForecastModel(
        estimator, 0.0, "pending", {}, fit_public_revenue_model(), expense_estimator
    )
    errors: dict[str, list[float]] = {
        "seasonal_naive": [],
        "gradient_boosting": [],
        "blend_50": [],
    }
    for business in validation:
        history = aggregate(business.request())
        for name, forecast in model.predict_candidates(history).items():
            errors[name].extend(np.abs(forecast - business.future_net).tolist())
    validation_mae = {name: float(np.mean(values)) for name, values in errors.items()}
    chosen = min(validation_mae, key=validation_mae.get)
    model.blend_weight = {
        "seasonal_naive": 0.0,
        "gradient_boosting": 1.0,
        "blend_50": 0.5,
    }[chosen]
    # Revenue estimators fit real targets only. Constrain candidate policies by
    # independent real validation, then choose the net-serving combination on
    # held-out-from-fitting synthetic businesses. This resolves proxy transfer
    # without claiming public revenues supply borrower costs or default labels.
    public = model.public_revenue_model
    real_estimator_fingerprint = joblib.hash(
        (public.estimator, public.residual_estimator, public.harmonic_estimator),
        hash_name="sha1",
    )
    real_recipe = real_component_recipe_digest()
    if real_recipe != FROZEN_REAL_RECIPE_SHA256:
        raise ValueError(
            "Frozen real revenue recipe changed; a new external audit is required"
        )
    real_validation = public.metadata["combined_validation"]
    naive_error = real_validation["seasonal_naive"]["normalized_mae"]
    qualified_revenue = [
        name
        for name in TRAINED_CANDIDATES
        if public.metadata["candidate_qualification"][name]
        and 1 - real_validation[name]["normalized_mae"] / naive_error >= 0.05
    ]
    if FROZEN_REAL_REVENUE_CANDIDATE not in qualified_revenue:
        raise ValueError("Frozen real revenue candidate no longer qualifies")
    public.selected = FROZEN_REAL_REVENUE_CANDIDATE
    validation_parts = []
    for business in validation:
        history = aggregate(business.request())
        synthetic = model.predict_synthetic(history)
        revenue_candidates = {public.selected: public.predict(history)}
        cost_projections = observed_expense_candidates(
            history, revenue_candidates[public.selected]
        )
        with threadpool_limits(limits=1):
            synthetic_expenses = np.maximum(
                expense_estimator.predict(feature_matrix(history))
                * normalizer(history),
                0,
            )
        cost_projections["synthetic_model"] = synthetic_expenses
        validation_parts.append(
            (business, history, synthetic, revenue_candidates, cost_projections)
        )
    joint_results = {}
    joint_policy_results = {}
    options = []
    policies = transfer_policies()
    expense_policies = expense_projection_policies()
    evaluation_candidates = [FROZEN_REAL_REVENUE_CANDIDATE]
    for revenue_name in evaluation_candidates:
        transfer_results = {}
        policy_results = {}
        for expense_name, expense_policy in expense_policies.items():
            errors = {name: [] for name in policies}
            macro_errors = {name: [] for name in policies}
            cohorts = {name: {} for name in policies}
            effective_weights = {name: [] for name in policies}
            for (
                business,
                history,
                synthetic,
                revenues,
                cost_projections,
            ) in validation_parts:
                revenue = revenues[revenue_name]
                expenses = cost_projections[expense_name]
                real_net = revenue - expenses
                for name, policy in policies.items():
                    weight = transfer_policy_weight(history, policy)
                    forecast = (1 - weight) * synthetic + weight * real_net
                    error = float(np.mean(np.abs(forecast - business.future_net)))
                    errors[name].append(error)
                    macro_errors[name].append(error / normalizer(history))
                    effective_weights[name].append(weight)
                    cohorts[name].setdefault(business.cohort, []).append(
                        error / normalizer(history)
                    )
            measured = {
                name: {
                    "policy": policy,
                    "expense_policy": expense_policy,
                    "pooled_mae_index": float(np.mean(errors[name])),
                    "macro_normalized_mae": float(np.mean(macro_errors[name])),
                    "by_cohort_macro_normalized_mae": {
                        cohort: float(np.mean(values))
                        for cohort, values in cohorts[name].items()
                    },
                    "effective_real_weights": effective_weight_summary(
                        effective_weights[name]
                    ),
                }
                for name, policy in policies.items()
            }
            results = {
                "pooled_mae_index": {
                    weight: measured[f"fixed_{weight:g}"]["pooled_mae_index"]
                    for weight in TRANSFER_WEIGHTS
                },
                "macro_normalized_mae": {
                    weight: measured[f"fixed_{weight:g}"]["macro_normalized_mae"]
                    for weight in TRANSFER_WEIGHTS
                },
                "by_cohort_macro_normalized_mae": {
                    weight: measured[f"fixed_{weight:g}"][
                        "by_cohort_macro_normalized_mae"
                    ]
                    for weight in TRANSFER_WEIGHTS
                },
            }
            transfer_results[expense_name] = results
            baseline = results["pooled_mae_index"][0.0]
            baseline_macro = results["macro_normalized_mae"][0.0]
            for name, row in measured.items():
                raw = row["pooled_mae_index"]
                macro = row["macro_normalized_mae"]
                cohort_gate = all(
                    value
                    <= results["by_cohort_macro_normalized_mae"][0.0][cohort] * 1.15
                    for cohort, value in row["by_cohort_macro_normalized_mae"].items()
                )
                development_eligible = name == "fixed_0" or (
                    revenue_name in qualified_revenue
                    and raw < baseline
                    and macro <= baseline_macro * 1.02
                    and cohort_gate
                )
                cohort_ratios = {
                    cohort: value
                    / results["by_cohort_macro_normalized_mae"][0.0][cohort]
                    for cohort, value in row["by_cohort_macro_normalized_mae"].items()
                }
                worst_cohort_ratio = max(cohort_ratios.values())
                robustness_eligible = (
                    worst_cohort_ratio <= DEVELOPMENT_COHORT_ERROR_RATIO
                )
                rejection_reasons = []
                if not development_eligible:
                    rejection_reasons.append("development_forecast_error_guard")
                if revenue_name != FROZEN_REAL_REVENUE_CANDIDATE:
                    rejection_reasons.append(
                        "real_candidate_frozen_before_external_audit"
                    )
                if row["effective_real_weights"]["mean"] < 0.55:
                    rejection_reasons.append("development_mean_real_share_below_55pct")
                if not robustness_eligible:
                    rejection_reasons.append(
                        "development_cohort_robustness_buffer_above_10pct"
                    )
                eligible = not rejection_reasons
                row["development_eligible"] = development_eligible
                row["by_cohort_error_ratio_vs_synthetic"] = cohort_ratios
                row["maximum_cohort_error_ratio_vs_synthetic"] = worst_cohort_ratio
                row["development_robustness_eligible"] = robustness_eligible
                row["eligible"] = eligible
                row["rejection_reasons"] = rejection_reasons
                if eligible:
                    options.append((raw, macro, revenue_name, expense_name, name))
            policy_results[expense_name] = measured
        joint_results[revenue_name] = transfer_results
        joint_policy_results[revenue_name] = policy_results
    if not options:
        raise ValueError("Validation produced no measured serving candidate")
    _, _, selected_revenue, selected_expense, selected_policy = min(options)
    model.expense_policy = expense_policies[selected_expense]
    model.expense_mode = (
        selected_expense
        if selected_expense in ("synthetic_model", "observed_cost_regression")
        else "observed_cost_projection"
    )
    model.transfer_policy = policies[selected_policy]
    model.transfer_weight = model.transfer_policy["base_weight"]
    public.selected = selected_revenue
    public.metadata["selected_candidate"] = selected_revenue
    public.metadata["selected_uses_trained_estimator"] = (
        selected_revenue in TRAINED_CANDIDATES
    )
    public.metadata["selected_for_serving_by"] = (
        "Joint validation only: real candidate must improve provider-balanced normalized MAE at least 5% versus seasonal and each provider may regress at most 2%; then select net pooled MAE with macro/cohort guards using synthetic validation, without fitting real estimator to synthetic targets"
    )
    transfer_results = joint_results[selected_revenue]
    selected_results = transfer_results[selected_expense]
    selected_policy_results = joint_policy_results[selected_revenue][selected_expense][
        selected_policy
    ]
    transfer_mae = selected_results["pooled_mae_index"]
    real_skill = 1 - real_validation[selected_revenue]["normalized_mae"] / naive_error
    model.selection = {
        "seed": SEED,
        "selected_candidate": chosen,
        "validation_mae_index": validation_mae,
        "selection_metric": "pooled validation-business future-12-month MAE",
        "training_businesses": TRAIN_COUNT,
        "validation_businesses": VALIDATION_COUNT,
        "training_origins": origins,
        "training_origin_variants": ["complete_month", "partial_month_excluded"],
        "training_examples": sum(len(part) for part in y_parts),
        "features": list(FEATURE_NAMES),
        "train_ids": sorted(train_ids),
        "validation_ids": sorted(validation_ids),
        "test_used_for_selection": False,
        "public_revenue_training": model.public_revenue_model.metadata,
        "expense_training": "Synthetic expense estimator fits actual generated training-business outflows only. All observation-based cost projections use only the scored borrower's past transactions; median-share projection assumes future costs scale with revenue and implicitly includes historical fixed costs. No public expense/default labels",
        "expense_mode": model.expense_mode,
        "selected_expense_policy": selected_expense,
        "expense_policy": model.expense_policy,
        "expense_projection_grid": expense_policies,
        "transfer_validation": transfer_results,
        "joint_transfer_validation": joint_results,
        "joint_policy_validation": joint_policy_results,
        "selected_transfer_policy": selected_policy,
        "selected_transfer_validation": selected_policy_results,
        "qualified_real_revenue_candidates": qualified_revenue,
        "minimum_development_mean_real_weight": 0.55,
        "maximum_development_cohort_error_ratio": DEVELOPMENT_COHORT_ERROR_RATIO,
        "development_weight_aggregation": "math.fsum(weights) / len(weights); no threshold rounding",
        "frozen_real_component": {
            "candidate": FROZEN_REAL_REVENUE_CANDIDATE,
            "recipe_sha256": real_recipe,
            "estimator_sha1": real_estimator_fingerprint,
            "estimator_fingerprint_scope": "Exact local continuity; not required to match across platforms because floating-point fitting may differ. Cross-platform builds enforce source/data/dependency recipe continuity instead.",
            "original_pipeline_source_sha256": "a93ef54f76f4117995aa9bce851ab4251e69c2f7ef337bdae03522b1191544db",
            "selection_timing": "Selected on original development validation before the external revenue audit; exact fitted estimators and candidate remain fixed during net-policy reselection",
        },
        "policy_reselection": {
            "reason": "Original guard_0.6_0.25_0.25 failed the first reserved engineering audit's majority-real requirement. Subsequent fixed50 policy and median-share12 guard75/25/25 policy each failed a cohort error guard in separate reserved audits. All three failed reports remain preserved. Original development candidates now require a tighter 10% cohort buffer and 55% mean real share, using accurate summation. No consumed audit target labels or cohort errors enter this selection; the unchanged final audit still allows 15% cohort regression. This fourth cycle is exploratory sequential development, not a fresh confirmatory experiment independent of previous aggregate rejection signals",
            "selection_data": "Original 60 synthetic development-validation businesses only",
            "final_audit_targets_used_for_reselection": False,
            "original_audit_is_consumed": True,
            "audit_thresholds_relaxed": False,
            "prior_structural_floor_attempt_rejected": True,
            "prior_reserved_engineering_audits_rejected": ["v2", "v3", "v4"],
            "development_net_reliability_experiments": {
                "selection_data": "Original 60 development-validation businesses and already observed transaction months only; no final audit labels",
                "comparison_scope": "Frozen adaptive_revenue_10 minus observed costs versus the unchanged synthetic reference; no fitted estimators or generator changes",
                "all_supported_origins": {
                    "history_cutoffs": "N-12, N-18, N-24; require at least 12 earlier observed months and 12 later already observed months",
                    "expense_candidates": 24,
                    "base_transfer_policies": 38,
                    "required_history_skill_margins": [0.0, 0.05, 0.10, 0.15],
                    "fallback_real_weights": [0.0, 0.25],
                    "pure_branch_grid_combinations": 7296,
                    "blended_branch_grid_combinations": 7296,
                    "majority_development_qualified_candidates_each": 0,
                    "maximum_mean_real_weight_each": 0.4125,
                    "rejection": "Neither local evidence rule meets the unchanged 55% development share requirement",
                },
                "latest_supported_origin": {
                    "history_cutoff": "Latest N-12 origin with at least 24 earlier observed months",
                    "supported_development_histories": 29,
                    "grid_combinations": 29184,
                    "comparisons": ["pure_real_branch", "serving_blend"],
                    "no_evidence_rules": ["preserve_validated_base", "cap_fallback"],
                    "required_history_skill_margins": [0.0, 0.05, 0.10, 0.15],
                    "fallback_real_weights": [0.0, 0.25],
                    "qualified_candidates_exist": True,
                    "qualified_example": {
                        "expense": "median_share6",
                        "transfer_policy": "guard_0.75_0.5_0.5",
                        "comparison": "serving_blend",
                        "no_evidence_rule": "preserve_validated_base",
                        "required_history_skill_margin": 0.10,
                        "fallback_real_weight": 0.25,
                        "pooled_mae_index": 100.81983073968303,
                        "macro_normalized_mae": 0.11681198105550526,
                        "mean_real_weight": 0.5541666666666667,
                        "maximum_cohort_error_ratio": 1.0617539064636081,
                    },
                    "rejection": "Considered but not served: extra per-request inference, 31 histories lacking supported local evidence, and slightly worse pooled development MAE than the simpler original-grid policy",
                },
            },
        },
        "joint_selected_revenue_candidate": selected_revenue,
        "serving_policy": {
            **model.transfer_policy,
            "selection": "validation_only",
            "real_revenue_candidate": selected_revenue,
            "expense_policy": model.expense_policy,
            "observed_history_only_expert_selection": selected_revenue.startswith(
                "adaptive_revenue_"
            ),
        },
        "validation_effective_real_weights": selected_policy_results[
            "effective_real_weights"
        ],
        "transfer_validation_macro_normalized_mae": selected_results[
            "macro_normalized_mae"
        ],
        "real_validation_skill_vs_seasonal": real_skill,
        "transfer_acceptance_gate": "Selected real revenue candidate must actively use its real-data-fitted estimator; provider-balanced validation normalized MAE improves seasonal naive by at least 5%; each real provider may regress no more than 2%; downstream synthetic validation pooled MAE must improve and macro normalized MAE may worsen no more than 2%. The original 15% development cohort error guard is preserved and selection additionally requires a tighter 10% development cohort buffer. Original development mean real contribution must be at least 55%, preserving a cushion above the unchanged audit mean50 requirement. Final audit cohort tolerance remains 15%; no audit threshold is relaxed. The externally audited real component stays unchanged. No test target labels enter policy selection.",
        "transfer_validation_mae_index": transfer_mae,
        "transfer_weight": model.transfer_weight,
        "serving_mode": (
            "real_revenue_observed_costs_blend"
            if model.expense_mode != "synthetic_model"
            else "real_revenue_synthetic_expenses_blend"
        )
        if model.transfer_weight
        else "synthetic_net_public_transfer_rejected",
        "transfer_selection_metric": "Same 60 held-out-from-fitting synthetic validation businesses, future-12-month pooled and macro normalized net MAE; real revenue policies qualified by provider-balanced real validation first, then all fixed/observed-history-guard net policies are selected on synthetic validation only. Regime routing uses history length and the observed recent-three/prior-three inflow ratio, with no future or cohort inputs; estimators remain fitted exclusively on actual real revenue. Legacy test sets are not fresh confirmation.",
        "source_sha256": pipeline_source_digest(),
        "public_calibration": {
            "source": "Uzbekistan SIAT retail aggregate turnover, CC BY 4.0",
            "training_years": [2020, 2021, 2022],
            "snapshot_calibration_sha256": calibration_digest(),
            "calibrated_cohorts": [
                "seasonal",
                "growing",
                "declining",
                "volatile_growth",
            ],
            "weight": 0.5,
            "future_actuals_used": False,
        },
    }
    # Source digest includes data generation, feature/scoring policy and settings.
    model.version = f"local-v4-{model.selection['source_sha256'][:12]}-{chosen}-public{round(100 * model.transfer_weight)}"
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", default=os.environ.get("ML_MODEL_PATH", "runtime/model.joblib")
    )
    args = parser.parse_args()
    model = fit_model()
    model.save(args.output)
    print(json.dumps({"model_version": model.version, **model.selection}, indent=2))


if __name__ == "__main__":
    main()
