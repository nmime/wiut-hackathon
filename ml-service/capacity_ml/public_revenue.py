"""Direct real-revenue training, independent geographic and temporal evaluation.

The neutral zero second series is a feature representation for revenue only;
it is never an assertion of zero borrower expenses.
"""

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .forecasting import MonthlyHistory, normalizer
from .international_data import build_international_cases, load_international_series
from .revenue_data import RevenueSeries, load_revenue_series, parse_month
from .revenue_features import (
    REVENUE_FEATURE_NAMES,
    revenue_baselines,
    revenue_feature_matrix,
)

PUBLIC_CANDIDATES = (
    "seasonal_naive",
    "trend_adjusted_seasonal",
    "damped_seasonal",
    "robust_harmonic",
    "gradient_boosting",
    "learned_residual",
    "residual_blend_25",
    "residual_blend_50",
    "harmonic_residual_25",
    "harmonic_residual_50",
    "history_shrinkage_25",
    "history_shrinkage_50",
)
TRAIN_END = parse_month("2025-12")


def revenue_history(history: MonthlyHistory) -> MonthlyHistory:
    return MonthlyHistory(
        history.months,
        history.inflow,
        np.zeros(len(history.inflow)),
        history.forecast_start,
        history.partial_month_excluded,
        history.partial_only,
    )


@dataclass
class PublicCase:
    identity: str
    sector: str
    group: str
    history: MonthlyHistory
    actual: np.ndarray


def make_case(
    series: RevenueSeries, target_start: int, horizon: int
) -> PublicCase | None:
    start = max(int(series.months[0]), target_start - 48)
    required = np.arange(start, target_start + horizon)
    mapping = dict(zip(series.months, series.values, strict=True))
    values = np.asarray([mapping.get(int(month), np.nan) for month in required])
    if target_start - start < 3 or np.any(~np.isfinite(values)) or np.any(values < 0):
        return None
    observed = values[:-horizon]
    if np.mean(observed[-12:]) <= 0:
        return None
    return PublicCase(
        series.identity,
        series.sector,
        series.group,
        MonthlyHistory(
            np.arange(start, target_start),
            observed,
            np.zeros(len(observed)),
            target_start,
        ),
        values[-horizon:],
    )


def build_cases(series: list[RevenueSeries], metadata: dict) -> tuple[dict, dict]:
    cases = {"train": [], "validation": [], "test_2025": [], "test_2026": []}
    exclusions = {key: 0 for key in cases}
    groups = metadata["geographic_groups"]
    for row in series:
        if row.group in groups["train"]:
            origins = [
                ("train", start, 12)
                for start in range(
                    max(int(row.months[0]) + 12, parse_month("2021-01")),
                    parse_month("2025-02"),
                )
            ]
            # New post-break service definitions have only three observed months
            # before a full 2025 target; include that explicitly, not old regimes.
            if row.sector in {"market_services", "accommodation_food"}:
                origins = [("train", parse_month("2025-01"), 12)]
        elif row.group in groups["validation"]:
            origins = [("validation", parse_month("2025-01"), 12)]
        elif row.group in groups["test"]:
            origins = [
                ("test_2025", parse_month("2025-01"), 12),
                ("test_2026", parse_month("2026-01"), 8),
            ]
        else:
            raise ValueError("Revenue series lacks a declared geographic partition")
        for split, origin, horizon in origins:
            case = make_case(row, origin, horizon)
            if case is None:
                exclusions[split] += 1
                continue
            if split == "train" and origin + horizon - 1 > TRAIN_END:
                raise ValueError("Real training target exceeds the 2025 boundary")
            cases[split].append(case)
    return cases, exclusions


@dataclass
class PublicRevenueModel:
    estimator: HistGradientBoostingRegressor
    selected: str
    metadata: dict
    residual_estimator: HistGradientBoostingRegressor | None = None

    def predict_candidates(self, history: MonthlyHistory) -> dict[str, np.ndarray]:
        history = revenue_history(history)
        if not np.any(history.inflow[-12:] > 0):
            return {name: np.zeros(12) for name in PUBLIC_CANDIDATES}
        baselines = revenue_baselines(history)
        seasonal = baselines["seasonal_naive"]
        prior = float(np.sum(history.inflow[-24:-12]))
        growth = (
            float(np.sum(history.inflow[-12:])) / prior
            if len(history.inflow) >= 24 and prior > 0
            else 1.0
        )
        features = revenue_feature_matrix(history)
        scale = normalizer(history)
        with threadpool_limits(limits=1):
            boosting = np.maximum(self.estimator.predict(features) * scale, 0)
            if self.residual_estimator is None:
                raise ValueError("Missing real-only residual estimator")
            residual = np.clip(self.residual_estimator.predict(features), -2, 2)
        baseline = baselines["damped_seasonal"]
        learned = (
            np.maximum((baseline / scale + 0.05) * np.exp(residual) - 0.05, 0) * scale
        )
        return {
            **baselines,
            "trend_adjusted_seasonal": seasonal * growth,
            "gradient_boosting": boosting,
            "learned_residual": learned,
            "residual_blend_25": 0.75 * baseline + 0.25 * learned,
            "residual_blend_50": 0.5 * baseline + 0.5 * learned,
            "harmonic_residual_25": 0.75 * baselines["robust_harmonic"]
            + 0.25 * learned,
            "harmonic_residual_50": 0.5 * baselines["robust_harmonic"] + 0.5 * learned,
            "history_shrinkage_25": 0.75 * baseline + 0.25 * learned
            if len(history.months) >= 12
            else learned,
            "history_shrinkage_50": 0.5 * baseline + 0.5 * learned
            if len(history.months) >= 12
            else learned,
        }

    def predict(self, history: MonthlyHistory) -> np.ndarray:
        # Serving runs only the validation-selected component. Evaluators use
        # predict_candidates to compare the fixed grid without refitting it.
        history = revenue_history(history)
        if not np.any(history.inflow[-12:] > 0):
            return np.zeros(12)
        baselines = revenue_baselines(history)
        if self.selected in baselines:
            return baselines[self.selected]
        if self.selected == "trend_adjusted_seasonal":
            prior = float(np.sum(history.inflow[-24:-12]))
            growth = (
                float(np.sum(history.inflow[-12:])) / prior
                if len(history.inflow) >= 24 and prior > 0
                else 1.0
            )
            return baselines["seasonal_naive"] * growth
        features = revenue_feature_matrix(history)
        scale = normalizer(history)
        if self.selected == "gradient_boosting":
            with threadpool_limits(limits=1):
                return np.maximum(self.estimator.predict(features) * scale, 0)
        if self.residual_estimator is None:
            raise ValueError("Missing real-only residual estimator")
        with threadpool_limits(limits=1):
            residual = np.clip(self.residual_estimator.predict(features), -2, 2)
        baseline = baselines["damped_seasonal"]
        learned = (
            np.maximum((baseline / scale + 0.05) * np.exp(residual) - 0.05, 0) * scale
        )
        if self.selected.startswith("history_shrinkage_"):
            weight = {"history_shrinkage_25": 0.25, "history_shrinkage_50": 0.5}.get(
                self.selected
            )
            if weight is None:
                raise ValueError("Invalid real revenue candidate")
            if len(history.months) < 12:
                return learned
            return (1 - weight) * baseline + weight * learned
        if self.selected.startswith("harmonic_residual_"):
            weight = {"harmonic_residual_25": 0.25, "harmonic_residual_50": 0.5}.get(
                self.selected
            )
            if weight is None:
                raise ValueError("Invalid real revenue candidate")
            return (1 - weight) * baselines["robust_harmonic"] + weight * learned
        weight = {
            "learned_residual": 1.0,
            "residual_blend_25": 0.25,
            "residual_blend_50": 0.5,
        }.get(self.selected)
        if weight is None:
            raise ValueError("Invalid real revenue candidate")
        return (1 - weight) * baseline + weight * learned


def metrics(cases: list[PublicCase], predictions: list[np.ndarray]) -> dict:
    if not cases:
        raise ValueError("No valid public revenue evaluation cases")
    actual = np.concatenate([case.actual for case in cases])
    predicted = np.concatenate(predictions)
    if actual.shape != predicted.shape or not np.all(np.isfinite(predicted)):
        raise ValueError("Public forecast metrics require aligned finite predictions")
    if not np.all(np.isfinite(actual)) or np.any(actual < 0):
        raise ValueError("Invalid public actuals must be excluded, never clipped")
    errors = np.abs(actual - predicted)
    scales = np.concatenate(
        [np.full(len(case.actual), normalizer(case.history)) for case in cases]
    )
    positive = actual > 0
    return {
        "cases": len(cases),
        "months": len(actual),
        "mae_million_uzs": float(np.mean(errors)),
        "normalized_mae": float(np.mean(errors / scales)),
        "mape_positive_actual_pct": float(
            np.mean(errors[positive] / actual[positive]) * 100
        )
        if np.any(positive)
        else None,
        "mape_excluded_zero_months": int(np.count_nonzero(~positive)),
        "wape_pct": float(np.sum(errors) / np.sum(actual) * 100)
        if np.sum(actual) > 0
        else None,
    }


def measure(model: PublicRevenueModel, cases: list[PublicCase]) -> dict:
    parts = {name: [] for name in PUBLIC_CANDIDATES}
    for case in cases:
        for name, prediction in model.predict_candidates(case.history).items():
            parts[name].append(prediction[: len(case.actual)])
    return {name: metrics(cases, predictions) for name, predictions in parts.items()}


def fit_public_revenue_model(
    dataset: tuple[list[RevenueSeries], dict] | None = None,
) -> PublicRevenueModel:
    series, metadata = dataset if dataset is not None else load_revenue_series()
    legacy_cases, exclusions = build_cases(series, metadata)
    provider_train = {"uzbekistan_siat": legacy_cases["train"]}
    provider_validation = {"uzbekistan_siat": legacy_cases["validation"]}
    international_metadata = None
    international_exclusions = {}
    if dataset is None:
        international = load_international_series()
        international_metadata = international[1]
        for split, destination in (
            ("train", provider_train),
            ("validation", provider_validation),
        ):
            rows, omitted = build_international_cases(split, dataset=international)
            international_exclusions[split] = omitted
            for provider in international_metadata["providers"]:
                destination[provider] = [
                    case for case in rows if case.identity.startswith(provider + ":")
                ]
    train_cases = sum(provider_train.values(), [])
    x = np.vstack([revenue_feature_matrix(case.history) for case in train_cases])
    y = np.concatenate([case.actual / normalizer(case.history) for case in train_cases])
    # Each provider contributes equal total loss weight. Native AUD/CAD/UZS
    # quantities are normalized within history and never pooled as currency.
    sample_weights = np.concatenate(
        [
            np.full(
                sum(len(case.actual) for case in rows),
                len(y) / len(provider_train) / sum(len(case.actual) for case in rows),
            )
            for rows in provider_train.values()
        ]
    )
    estimator = HistGradientBoostingRegressor(
        loss="absolute_error",
        learning_rate=0.08,
        max_iter=160,
        max_leaf_nodes=15,
        min_samples_leaf=25,
        l2_regularization=2,
        early_stopping=False,
        random_state=20261010,
    )
    residual_targets = np.concatenate(
        [
            np.log(case.actual / normalizer(case.history) + 0.05)
            - np.log(
                revenue_baselines(case.history)["damped_seasonal"]
                / normalizer(case.history)
                + 0.05
            )
            for case in train_cases
        ]
    )
    with threadpool_limits(limits=1):
        estimator.fit(x, y, sample_weight=sample_weights)
    # This finite complexity grid and per-provider two-percent regression guard
    # are frozen before any fresh international test outcomes are examined.
    parameter_grid = (
        {
            "max_leaf_nodes": 15,
            "min_samples_leaf": 25,
            "l2_regularization": 2,
            "max_iter": 160,
        },
        {
            "max_leaf_nodes": 7,
            "min_samples_leaf": 80,
            "l2_regularization": 10,
            "max_iter": 160,
        },
        {
            "max_leaf_nodes": 15,
            "min_samples_leaf": 80,
            "l2_regularization": 10,
            "max_iter": 240,
        },
        {
            "max_leaf_nodes": 15,
            "min_samples_leaf": 80,
            "l2_regularization": 10,
            "max_iter": 160,
        },
        {
            "max_leaf_nodes": 31,
            "min_samples_leaf": 50,
            "l2_regularization": 5,
            "max_iter": 160,
        },
    )
    trials = []
    winner = None
    for parameters in parameter_grid:
        settings = {**estimator.get_params(), **parameters}
        residual_estimator = HistGradientBoostingRegressor(**settings)
        with threadpool_limits(limits=1):
            residual_estimator.fit(x, residual_targets, sample_weight=sample_weights)
        candidate = PublicRevenueModel(
            estimator, "seasonal_naive", metadata, residual_estimator
        )
        by_provider = {}
        for provider, rows in provider_validation.items():
            errors = {name: [] for name in PUBLIC_CANDIDATES}
            for case in rows:
                for name, prediction in candidate.predict_candidates(
                    case.history
                ).items():
                    errors[name].append(
                        float(
                            np.mean(
                                np.abs(case.actual - prediction[: len(case.actual)])
                            )
                            / normalizer(case.history)
                        )
                    )
            by_provider[provider] = {
                name: {
                    "normalized_mae": float(np.mean(values)),
                    "cases": len(rows),
                    "months": sum(len(case.actual) for case in rows),
                }
                for name, values in errors.items()
            }
        combined = {
            name: {
                "normalized_mae": float(
                    np.mean(
                        [
                            parts[name]["normalized_mae"]
                            for parts in by_provider.values()
                        ]
                    )
                ),
                "by_provider": {
                    provider: parts[name] for provider, parts in by_provider.items()
                },
            }
            for name in PUBLIC_CANDIDATES
        }
        qualification = {
            name: all(
                parts[name]["normalized_mae"]
                <= parts["seasonal_naive"]["normalized_mae"] * 1.02
                for parts in by_provider.values()
            )
            for name in PUBLIC_CANDIDATES
        }
        selected = min(
            (name for name in PUBLIC_CANDIDATES if qualification[name]),
            key=lambda name: combined[name]["normalized_mae"],
        )
        trials.append(
            {
                "residual_parameters": parameters,
                "validation": combined,
                "candidate_qualification": qualification,
                "selected_candidate": selected,
            }
        )
        score = combined[selected]["normalized_mae"]
        if winner is None or score < winner[0]:
            winner = (score, candidate, combined, qualification, parameters)
            candidate.selected = selected
    if winner is None:
        raise ValueError("No qualified real revenue validation candidate")
    _, model, combined_validation, qualification, residual_parameters = winner
    validation = measure(model, legacy_cases["validation"])
    training_by_provider = {
        provider: {
            "cases": len(rows),
            "examples": sum(len(case.actual) for case in rows),
            "series": len({case.identity for case in rows}),
            "unique_target_observations": len(
                {
                    (case.identity, case.history.forecast_start + offset)
                    for case in rows
                    for offset in range(len(case.actual))
                }
            ),
            "latest_target_month_id": max(
                case.history.forecast_start + len(case.actual) - 1 for case in rows
            ),
            "training_loss_weight": 1 / len(provider_train),
        }
        for provider, rows in provider_train.items()
    }
    model.metadata = {
        **metadata,
        "sources": metadata["sources"]
        + (international_metadata["sources"] if international_metadata else []),
        "selected_candidate": model.selected,
        "candidate_qualification": qualification,
        "provider_regression_guard": "Each provider validation normalized MAE may worsen no more than 2% versus seasonal naive; select smallest qualified provider-balanced normalized MAE",
        "residual_hyperparameters": residual_parameters,
        "parameter_validation": trials,
        "selected_uses_trained_estimator": model.selected
        in {
            "gradient_boosting",
            "learned_residual",
            "residual_blend_25",
            "residual_blend_50",
            "harmonic_residual_25",
            "harmonic_residual_50",
            "history_shrinkage_25",
            "history_shrinkage_50",
        },
        "features": list(REVENUE_FEATURE_NAMES),
        "validation": combined_validation if international_metadata else validation,
        "uzbekistan_validation": validation,
        "combined_validation": combined_validation,
        "training_cases": len(train_cases),
        "training_examples": len(y),
        "training_series": len({case.identity for case in train_cases}),
        "training_unique_target_observations": sum(
            parts["unique_target_observations"]
            for parts in training_by_provider.values()
        ),
        "training_by_provider": training_by_provider,
        "uzbekistan_training_examples": training_by_provider["uzbekistan_siat"][
            "examples"
        ],
        "training_target_end": "2025-12 (Uzbekistan); earlier provider-specific boundaries in international_protocols",
        "validation_target": "Provider-specific geographic and terminal-time validation; Uzbekistan January-December 2025 is legacy development validation",
        "test_protocol": "Fresh independent international geographic plus terminal-year holdout is constructed explicitly only after model freeze; previous Uzbekistan and synthetic test outcomes are legacy regression benchmarks.",
        "selection_metric": "Provider-balanced macro per-history-normalized validation MAE; training loss weight equal by provider; no final test outcomes used",
        "exclusions": exclusions,
        "international_exclusions": international_exclusions,
        "international_data_sha256": international_metadata["data_sha256"]
        if international_metadata
        else None,
        "international_protocols": international_metadata["protocols"]
        if international_metadata
        else {},
        "international_eligible_series": international_metadata["series"]
        if international_metadata
        else 0,
        "international_observations": international_metadata["observations"]
        if international_metadata
        else 0,
        "international_nonnull_published_observations": international_metadata[
            "nonnull_published_observations"
        ]
        if international_metadata
        else 0,
        "international_missing_suppressed_or_unreliable_observations": international_metadata[
            "missing_suppressed_or_unreliable_observations"
        ]
        if international_metadata
        else 0,
        "training_earliest_target": min(
            case.history.forecast_start for case in train_cases
        ),
        "training_latest_target": max(
            case.history.forecast_start + 11 for case in train_cases
        ),
        "test_used_for_training_or_selection": False,
        "temporal_scope": "Holdouts are provider-local terminal years; Uzbekistan training through December 2025 overlaps some Australian/Canadian holdout dates. No absolute year, provider identity or cross-country shock covariates are features; this is not a globally chronological unseen-future test.",
        "limitations": "Original retail turnover and service value are aggregate revenue proxies, not independent firm cash receipts. Native currency units remain separate and only dimensionless errors are pooled. Survey revisions, correlated economic shocks, Uzbekistan short post-methodology histories, and cross-country aggregate-to-borrower transfer limit claims. No real costs, defaults or repayments are supplied.",
    }
    return model
