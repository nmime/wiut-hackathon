"""Temporal revenue benchmark on public SIAT retail turnover, separate from /score."""

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .forecasting import (
    FEATURE_NAMES,
    MonthlyHistory,
    feature_matrix,
    normalizer,
    seasonal_forecast,
)
from .generator import month_id
from .public_data import load_public_data

SEED = 20261010
CANDIDATES = ("seasonal_naive", "trend_adjusted_seasonal", "gradient_boosting")
FIRST_MONTH = month_id(2020, 1)
TRAIN_LAST_MONTH = month_id(2022, 12)


def month_label(value: int) -> str:
    return f"{value // 12:04d}-{value % 12 + 1:02d}"


def parse_month(value: str) -> int:
    parts = value.split("-")
    if (
        len(parts) != 2
        or len(parts[0]) != 4
        or len(parts[1]) != 2
        or not all(part.isdigit() for part in parts)
        or not 1 <= int(parts[0]) <= 9999
        or not 1 <= int(parts[1]) <= 12
    ):
        raise ValueError(f"Invalid observation month: {value!r}")
    return month_id(int(parts[0]), int(parts[1]))


@dataclass
class RevenueCase:
    code: str
    region: str
    history: MonthlyHistory
    actual: np.ndarray

    @property
    def target_year(self) -> int:
        return self.history.forecast_start // 12

    def description(self) -> dict:
        return {
            "code": self.code,
            "region": self.region,
            "history_start": month_label(int(self.history.months[0])),
            "history_end": month_label(int(self.history.months[-1])),
            "target_start": month_label(self.history.forecast_start),
            "target_end": month_label(self.history.forecast_start + 11),
        }


def build_cases(dataset: dict) -> tuple[dict[str, list[RevenueCase]], list[dict]]:
    """Never fill/clip missing or negative increments or read later target years."""
    cases: dict[str, list[RevenueCase]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    exclusions = []
    seen_codes = set()
    for series in dataset["series"]:
        code, region = str(series["code"]), series["region"]
        if code in seen_codes:
            raise ValueError(f"Duplicate series code: {code}")
        seen_codes.add(code)
        if series["is_national_total"]:
            continue
        values = {}
        for observation in series["observations"]:
            month = parse_month(observation["month"])
            if month in values:
                raise ValueError(f"Duplicate observation: {code} {month_label(month)}")
            value = observation["monthly_million_uzs"]
            values[month] = (
                float(value)
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                else float("nan")
            )
        origins = [
            ("train", start) for start in range(FIRST_MONTH + 12, TRAIN_LAST_MONTH - 10)
        ] + [
            ("validation", month_id(2023, 1)),
            ("test", month_id(2024, 1)),
            ("test", month_id(2025, 1)),
        ]
        for split, start in origins:
            required_months = np.arange(FIRST_MONTH, start + 12)
            issues = []
            for month in required_months:
                value = values.get(int(month))
                reason = (
                    "missing_month"
                    if value is None
                    else "nonfinite_monthly_increment"
                    if not np.isfinite(value)
                    else "negative_monthly_increment"
                    if value < 0
                    else None
                )
                if reason:
                    issues.append({"month": month_label(int(month)), "reason": reason})
            if issues:
                exclusions.append(
                    {
                        "split": split,
                        "code": code,
                        "region": region,
                        "target_start": month_label(start),
                        "target_end": month_label(start + 11),
                        "issues": issues,
                    }
                )
                continue
            observed = np.asarray([values[int(month)] for month in required_months])
            history_values = observed[:-12]
            history = MonthlyHistory(
                months=np.arange(FIRST_MONTH, start),
                inflow=history_values,
                # Generic single-series features subtract this neutral array.
                # It does not assert that businesses have zero expenses.
                outflow=np.zeros(len(history_values)),
                forecast_start=start,
            )
            cases[split].append(RevenueCase(code, region, history, observed[-12:]))
    return cases, exclusions


def fit_public_model(cases: list[RevenueCase]) -> HistGradientBoostingRegressor:
    if not cases:
        raise ValueError("No valid pre-2023 training cases")
    x_parts, y_parts = [], []
    for case in cases:
        if (
            int(case.history.months[-1]) >= case.history.forecast_start
            or case.history.forecast_start + 11 > TRAIN_LAST_MONTH
        ):
            raise ValueError("Public training case crosses its temporal boundary")
        x_parts.append(feature_matrix(case.history))
        y_parts.append(case.actual / normalizer(case.history))
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
    return estimator


def predict_candidates(
    estimator: HistGradientBoostingRegressor, history: MonthlyHistory
) -> dict[str, np.ndarray]:
    seasonal = seasonal_forecast(history)
    previous_year = float(np.sum(history.inflow[-24:-12]))
    growth_ratio = (
        float(np.sum(history.inflow[-12:])) / previous_year
        if len(history.inflow) >= 24 and previous_year > 0
        else 1.0
    )
    with threadpool_limits(limits=1):
        boosting = estimator.predict(feature_matrix(history)) * normalizer(history)
    return {
        "seasonal_naive": seasonal,
        "trend_adjusted_seasonal": seasonal * growth_ratio,
        "gradient_boosting": boosting,
    }


def forecast_metrics(actual: np.ndarray, forecast: np.ndarray) -> dict:
    if actual.shape != forecast.shape or actual.size == 0:
        raise ValueError("Metrics require equal, nonempty actual/forecast arrays")
    if not np.all(np.isfinite(actual)) or not np.all(np.isfinite(forecast)):
        raise ValueError("Metrics require finite values")
    if np.any(actual < 0):
        raise ValueError("Negative source increments must be excluded, never clipped")
    errors = np.abs(actual - forecast)
    positive = actual > 0
    denominator = float(np.sum(actual))
    return {
        "mae_million_uzs": float(np.mean(errors)),
        "mape_positive_actual_pct": float(
            np.mean(errors[positive] / actual[positive]) * 100
        )
        if np.any(positive)
        else None,
        "mape_included_months": int(np.count_nonzero(positive)),
        "mape_excluded_zero_months": int(np.count_nonzero(~positive)),
        "wape_pct": float(np.sum(errors) / denominator * 100)
        if denominator > 0
        else None,
        "wape_denominator_million_uzs": denominator,
        "months": int(actual.size),
    }


def measure_cases(
    estimator: HistGradientBoostingRegressor, cases: list[RevenueCase]
) -> dict:
    if not cases:
        raise ValueError("No valid evaluation cases")
    actual = np.concatenate([case.actual for case in cases])
    candidate_parts: dict[str, list[np.ndarray]] = {name: [] for name in CANDIDATES}
    for case in cases:
        for name, prediction in predict_candidates(estimator, case.history).items():
            candidate_parts[name].append(prediction)
    return {
        "region_year_cases": len(cases),
        "regions": len({case.code for case in cases}),
        "candidates": {
            name: forecast_metrics(actual, np.concatenate(parts))
            for name, parts in candidate_parts.items()
        },
    }


def select_candidate(validation: dict) -> str:
    """The selection API receives validation metrics only, never test metrics."""
    return min(
        CANDIDATES,
        key=lambda name: validation["candidates"][name]["mae_million_uzs"],
    )


def evaluate(dataset: dict | None = None) -> dict:
    dataset = load_public_data() if dataset is None else dataset
    cases, exclusions = build_cases(dataset)
    estimator = fit_public_model(cases["train"])
    validation = measure_cases(estimator, cases["validation"])
    selected = select_candidate(validation)
    # Freeze parameters and selection before measuring test outcomes.
    test = measure_cases(estimator, cases["test"])
    per_year = {
        str(year): measure_cases(
            estimator, [case for case in cases["test"] if case.target_year == year]
        )
        for year in (2024, 2025)
    }
    canonical_snapshot = json.dumps(dataset, sort_keys=True, separators=(",", ":"))
    return {
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "scope": "Public aggregate monthly retail turnover revenue forecasting only; not borrower payment capacity, default probability, or repayment validation",
        "source": dataset.get("source", {}),
        "snapshot_canonical_sha256": hashlib.sha256(
            canonical_snapshot.encode()
        ).hexdigest(),
        "protocol": {
            "training_years": [2020, 2021, 2022],
            "validation_years": [2023],
            "held_out_test_years": [2024, 2025],
            "unused_future_years": [2026],
            "temporal_holdout": True,
            "entity_disjoint": False,
            "national_total_excluded": True,
            "test_used_for_training_or_selection": False,
            "history_policy": "Contiguous observations from 2020-01 to the month before each forecast; exclude a case if any history or target increment is missing, nonfinite or negative; no clipping or imputation",
            "test_history_policy": "Annual January forecasts: 2024 uses observations through 2023-12; 2025 uses observations through 2024-12. Parameters and validation-selected candidate stay fixed; only observed input history updates",
            "training_origin_policy": "Monthly rolling origins with at least 12 historical months, 12-month targets entirely within 2020-2022; overlapping targets are training examples, not independent evaluation samples",
            "selection_metric": "Pooled 2023 validation MAE in million UZS; absolute errors favor larger regions. MAPE and per-year results reported separately",
            "mape_policy": "Mean absolute percentage error over actual>0 monthly revenue; exact zero actuals excluded and counted, negative source increments exclude the entire affected case",
            "features": list(FEATURE_NAMES),
            "single_series_feature_mapping": "Observed revenue is the generic helper's inflow/net series. Its zero subtraction array is a mathematical neutral value, not observed or invented business expense data. No margins, loan labels, or credit outcomes are created",
            "model_separation": "Independent in-memory public revenue estimator; never saved as the synthetic capacity model artifact or used by /score",
            "trend_baseline": "Last year's same-month turnover multiplied by (latest 12-month turnover sum / previous 12-month sum); ratio=1 with fewer than 24 observations or zero previous-year total",
        },
        "training": {
            "seed": SEED,
            "estimator": "HistGradientBoostingRegressor, absolute_error loss",
            "hyperparameters": {
                "learning_rate": 0.08,
                "max_iter": 160,
                "max_leaf_nodes": 15,
                "l2_regularization": 2.0,
                "min_samples_leaf": 25,
                "early_stopping": False,
            },
            "regions": len({case.code for case in cases["train"]}),
            "rolling_origins": len(cases["train"]),
            "training_examples": len(cases["train"]) * 12,
            "latest_history_month": month_label(
                max(int(case.history.months[-1]) for case in cases["train"])
            ),
            "earliest_target_month": month_label(
                min(case.history.forecast_start for case in cases["train"])
            ),
            "latest_target_month": month_label(
                max(case.history.forecast_start + 11 for case in cases["train"])
            ),
        },
        "selection": {
            "selected_candidate": selected,
            "test_used_for_selection": False,
            "validation": validation,
        },
        "held_out_test": test,
        "held_out_test_by_year": per_year,
        "selected_held_out_test": test["candidates"][selected],
        "exclusions": exclusions,
        "evaluated_cases": {
            split: [case.description() for case in cases[split]]
            for split in ("validation", "test")
        },
        "limitations": [
            "Regions repeat across years. This is a temporal regional revenue benchmark, not an unseen-business test; the separate synthetic evaluation is business-disjoint.",
            "Current published snapshot may contain historical revisions. Release-vintage data are unavailable, so this is not a fully vintage-correct historical backtest.",
            "Turnover is nominal aggregate revenue in published million UZS, without expenses, inflation adjustment, borrower balances, payment outcomes, or default labels.",
            "Only 13 valid regional cases per evaluation year remain in this snapshot. Growth, reporting changes and regional aggregation limit transfer to individual businesses.",
            "Public benchmark results do not validate the capacity heuristic, its confidence, or adaptive repayment safety. No bank production-performance claim is made.",
        ],
    }


def markdown_report(result: dict) -> str:
    source = result["source"]
    selected = result["selection"]["selected_candidate"]
    lines = [
        "# Public Uzbekistan retail revenue benchmark",
        "",
        f"Measured {result['measured_at_utc']}. This benchmark trains a separate revenue forecaster on actual public monthly retail turnover. It does not measure borrower payment capacity or repayment performance.",
        "",
        f"Source: [{source.get('publisher', 'SIAT retail data')}]({source.get('landing_url', 'https://siat.stat.uz/data/2699/?lang=en')}), indicator {source.get('indicator', '1.07.02.0002')}; [{source.get('license', 'CC BY 4.0')}]({source.get('license_url', 'https://creativecommons.org/licenses/by/4.0/')}). Published year-to-date totals become monthly increments by within-year differences and a January reset. Units remain **million UZS**.",
        "",
        "Train on 2020–2022 only, choose once by pooled 2023 validation MAE, and evaluate fixed parameters/candidate on 2024 and 2025. Regions repeat across years, so this is a **temporal holdout**, not an entity-disjoint test. Each January forecast uses history observed before that year; 2025 may use actual 2024 history without retraining. The national total is excluded to avoid duplicating regional observations. 2026 is unused.",
        "",
        f"Training: {result['training']['regions']} regions, {result['training']['rolling_origins']} rolling origins and {result['training']['training_examples']} horizon examples. Twelve-month targets end no later than {result['training']['latest_target_month']}; overlapping training targets are not independent evaluation samples. Fixed seed {SEED}; boosting parameters are listed in the JSON report.",
        "",
        f"Validation selected **{selected}**. All candidates remain visible below; test performance does not change selection. MAE weights absolute revenue errors and therefore favors larger regions. MAPE uses actual>0 observations only; zero denominators are counted separately.",
        "",
        "| Split | Candidate | Regions / cases | Months | MAE (million UZS) | MAPE (%) | MAPE included / excluded |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    measurements = {
        "Validation 2023": result["selection"]["validation"],
        "Held-out 2024–2025": result["held_out_test"],
        **{
            f"Held-out {year}": value
            for year, value in result["held_out_test_by_year"].items()
        },
    }
    for split, measurement in measurements.items():
        for candidate in CANDIDATES:
            metrics = measurement["candidates"][candidate]
            mape = metrics["mape_positive_actual_pct"]
            mape_text = f"{mape:.2f}" if mape is not None else "unavailable"
            lines.append(
                f"| {split} | {candidate} | {measurement['regions']} / {measurement['region_year_cases']} | {metrics['months']} | {metrics['mae_million_uzs']:.2f} | {mape_text} | {metrics['mape_included_months']} / {metrics['mape_excluded_zero_months']} |"
            )
    lines += [
        "",
        "Seasonal naive repeats the same calendar month from the previous year. Trend-adjusted seasonal multiplies it by the latest annual turnover growth ratio. Gradient boosting uses the existing lag/calendar feature helpers with revenue as a single series and a neutral subtraction array; this is not expense data. This in-memory model never replaces the synthetic `/score` model.",
        "",
        f"Excluded {len(result['exclusions'])} region-origin cases due to invalid or missing source increments; no clipping, imputation, or invented labels. The current snapshot's negative Fergana 2023-11 increment invalidates its 2023 target and subsequent full-history forecasts in 2024 and 2025. Exact exclusion records and all evaluated histories are in the JSON report.",
        "",
        "Limitations:",
        "",
        *[f"- {limitation}" for limitation in result["limitations"]],
        "",
        "Reproduce offline from the committed source snapshot:",
        "",
        "```sh",
        "cd ml-service",
        "uv run python -m capacity_ml.evaluate_public",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="reports")
    args = parser.parse_args()
    result = evaluate()
    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "public-metrics.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (destination / "public-metrics.md").write_text(
        markdown_report(result), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "selected_candidate": result["selection"]["selected_candidate"],
                "held_out_test": result["selected_held_out_test"],
                "exclusions": len(result["exclusions"]),
                "reports": str(destination.resolve()),
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
