"""Direct real-revenue training, independent geographic and temporal evaluation.

The neutral zero second series is a feature representation for revenue only;
it is never an assertion of zero borrower expenses.
"""

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .forecasting import MonthlyHistory, feature_matrix, normalizer, seasonal_forecast
from .revenue_data import RevenueSeries, load_revenue_series, parse_month

PUBLIC_CANDIDATES = ("seasonal_naive", "trend_adjusted_seasonal", "gradient_boosting")
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

    def predict_candidates(self, history: MonthlyHistory) -> dict[str, np.ndarray]:
        history = revenue_history(history)
        seasonal = np.maximum(seasonal_forecast(history), 0)
        prior = float(np.sum(history.inflow[-24:-12]))
        growth = (
            float(np.sum(history.inflow[-12:])) / prior
            if len(history.inflow) >= 24 and prior > 0
            else 1.0
        )
        with threadpool_limits(limits=1):
            boosting = np.maximum(
                self.estimator.predict(feature_matrix(history)) * normalizer(history), 0
            )
        return {
            "seasonal_naive": seasonal,
            "trend_adjusted_seasonal": seasonal * growth,
            "gradient_boosting": boosting,
        }

    def predict(self, history: MonthlyHistory) -> np.ndarray:
        return self.predict_candidates(history)[self.selected]


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
    cases, exclusions = build_cases(series, metadata)
    x = np.vstack([feature_matrix(case.history) for case in cases["train"]])
    y = np.concatenate(
        [case.actual / normalizer(case.history) for case in cases["train"]]
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
    with threadpool_limits(limits=1):
        estimator.fit(x, y)
    model = PublicRevenueModel(estimator, "seasonal_naive", metadata)
    validation = measure(model, cases["validation"])
    model.selected = min(
        PUBLIC_CANDIDATES, key=lambda name: validation[name]["normalized_mae"]
    )
    model.metadata = {
        **metadata,
        "selected_candidate": model.selected,
        "validation": validation,
        "training_cases": len(cases["train"]),
        "training_examples": len(y),
        "training_series": len({case.identity for case in cases["train"]}),
        "training_unique_target_observations": len(
            {
                (case.identity, case.history.forecast_start + offset)
                for case in cases["train"]
                for offset in range(len(case.actual))
            }
        ),
        "training_target_end": "2025-12",
        "validation_target": "2025-01..2025-12 (held-out geographic groups)",
        "test_protocol": "Separate geographic groups: complete 2025 entity holdout and January-August 2026 future holdout. Last four 2026 forecasts are unobserved and never counted.",
        "selection_metric": "Validation-only historical-scale-normalized revenue MAE; no test outcomes used",
        "exclusions": exclusions,
        "training_earliest_target": min(
            case.history.forecast_start for case in cases["train"]
        ),
        "training_latest_target": max(
            case.history.forecast_start + 11 for case in cases["train"]
        ),
        "test_used_for_training_or_selection": False,
        "limitations": "Aggregate service value/turnover is a proxy for revenue, not bank cash receipts. Preliminary single-vintage revisions, COVID-era trade observations, three-month post-break service histories and overlapping service categories limit transfer claims. Geographic partitions keep all categories and parent/child observations of a region together.",
    }
    return model
