"""Train real revenue and synthetic expenses; select transfer on validation only."""

import argparse
import json
import os

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .forecasting import (
    FEATURE_NAMES,
    TRANSFER_WEIGHTS,
    ForecastModel,
    aggregate,
    feature_matrix,
    normalizer,
    pipeline_source_digest,
)
from .generator import SEED, TRAIN_COUNT, VALIDATION_COUNT, generate_split
from .public_data import calibration_digest
from .public_revenue import fit_public_revenue_model
from .schemas import ScoreRequest


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
    # Both revenue training and the downstream transfer gate use validation
    # only. The fixed grid includes conservative ten-percent transfer because
    # aggregate revenue patterns differ from individual bank cash receipts.
    transfer_results = {}
    for expense_mode in ("synthetic_model", "observed_cost_regression"):
        model.expense_mode = expense_mode
        errors = {weight: [] for weight in TRANSFER_WEIGHTS}
        macro_errors = {weight: [] for weight in TRANSFER_WEIGHTS}
        cohorts = {weight: {} for weight in TRANSFER_WEIGHTS}
        for business in validation:
            history = aggregate(business.request())
            for weight, forecast in model.predict_transfer_candidates(history).items():
                error = float(np.mean(np.abs(forecast - business.future_net)))
                errors[weight].append(error)
                macro_errors[weight].append(error / normalizer(history))
                cohorts[weight].setdefault(business.cohort, []).append(
                    error / normalizer(history)
                )
        transfer_results[expense_mode] = {
            "pooled_mae_index": {
                weight: float(np.mean(values)) for weight, values in errors.items()
            },
            "macro_normalized_mae": {
                weight: float(np.mean(values))
                for weight, values in macro_errors.items()
            },
            "by_cohort_macro_normalized_mae": {
                weight: {
                    cohort: float(np.mean(values)) for cohort, values in parts.items()
                }
                for weight, parts in cohorts.items()
            },
        }
    real_validation = model.public_revenue_model.metadata.get(
        "combined_validation", model.public_revenue_model.metadata["validation"]
    )
    public_selected = model.public_revenue_model.selected
    real_skill = (
        1
        - real_validation[public_selected]["normalized_mae"]
        / real_validation["seasonal_naive"]["normalized_mae"]
    )
    options = []
    for expense_mode, results in transfer_results.items():
        baseline = results["pooled_mae_index"][0.0]
        baseline_macro = results["macro_normalized_mae"][0.0]
        for weight in TRANSFER_WEIGHTS:
            raw = results["pooled_mae_index"][weight]
            macro = results["macro_normalized_mae"][weight]
            eligible = weight == 0 or (
                model.public_revenue_model.metadata["selected_uses_trained_estimator"]
                and real_skill >= 0.05
                and raw < baseline
                and macro <= baseline_macro * 1.02
            )
            if eligible:
                options.append((raw, macro, expense_mode, weight))
    _, _, model.expense_mode, model.transfer_weight = min(options)
    selected_results = transfer_results[model.expense_mode]
    transfer_mae = selected_results["pooled_mae_index"]
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
        "expense_training": "Actual generated outflows from synthetic training businesses only; the optional observation-based cost regression is fitted only to the scored borrower's past inflow/outflow transactions. No public expense/default labels",
        "expense_mode": model.expense_mode,
        "transfer_validation": transfer_results,
        "transfer_validation_macro_normalized_mae": selected_results[
            "macro_normalized_mae"
        ],
        "real_validation_skill_vs_seasonal": real_skill,
        "transfer_acceptance_gate": "Selected real revenue candidate must actively use its real-data-fitted estimator; provider-balanced validation normalized MAE improves seasonal naive by at least 5%; downstream synthetic validation pooled MAE must improve and macro normalized MAE may worsen no more than 2%. No test labels enter acceptance.",
        "transfer_validation_mae_index": transfer_mae,
        "transfer_weight": model.transfer_weight,
        "serving_mode": (
            "real_revenue_observed_costs_blend"
            if model.expense_mode == "observed_cost_regression"
            else "real_revenue_synthetic_expenses_blend"
        )
        if model.transfer_weight
        else "synthetic_net_public_transfer_rejected",
        "transfer_selection_metric": "Same 60 held-out-from-fitting synthetic validation businesses, future-12-month pooled and macro normalized net MAE; real revenue candidate chosen separately by provider-balanced real entity/time validation only. Legacy test sets are not fresh confirmation.",
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
    model.version = f"local-v3-{model.selection['source_sha256'][:12]}-{chosen}-public{round(100 * model.transfer_weight)}"
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
