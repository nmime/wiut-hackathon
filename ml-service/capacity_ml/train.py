"""Rebuild artifact from fixed-seed synthetic train/validation businesses only."""

import argparse
import json
import os

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .forecasting import (
    FEATURE_NAMES,
    ForecastModel,
    aggregate,
    feature_matrix,
    normalizer,
    pipeline_source_digest,
)
from .generator import SEED, TRAIN_COUNT, VALIDATION_COUNT, generate_split
from .public_data import calibration_digest
from .schemas import ScoreRequest


def fit_model() -> ForecastModel:
    train = generate_split("train")
    validation = generate_split("validation")
    train_ids = {business.business_id for business in train}
    validation_ids = {business.business_id for business in validation}
    assert not train_ids & validation_ids
    x_parts, y_parts = [], []
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
        estimator.fit(np.vstack(x_parts), np.concatenate(y_parts))
    model = ForecastModel(estimator, 0.0, "pending", {})
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
    model.version = f"synthetic-v1-{model.selection['source_sha256'][:12]}-{chosen}"
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
