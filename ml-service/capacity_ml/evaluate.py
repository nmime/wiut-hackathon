"""Measure future actual events once model selection is already fixed."""

import argparse
import hashlib
import json
import os
import platform
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from .api import create_app
from .forecasting import ForecastModel, aggregate
from .generator import TEST_COUNT, generate_split
from .schemas import ScoreRequest, ScoreResponse
from .scoring import capacity_plan, score_request


def forecast_metrics(actual: np.ndarray, forecast: np.ndarray) -> dict:
    errors = np.abs(actual - forecast)
    mask = np.abs(actual) >= 1.0
    denominator = float(np.sum(np.abs(actual)))
    return {
        "mae_index": float(np.mean(errors)),
        "mape_abs_actual_ge_1_pct": float(
            np.mean(errors[mask] / np.abs(actual[mask])) * 100
        )
        if np.any(mask)
        else None,
        "mape_excluded_months": int(np.count_nonzero(~mask)),
        "wape_pct": float(np.sum(errors) / denominator * 100)
        if denominator > 0
        else None,
        "months": int(actual.size),
    }


def percent(values: list[bool]) -> float | None:
    return float(np.mean(values) * 100) if values else None


def summary(rows: list[dict]) -> dict:
    eligible = [row for row in rows if row["principal"] > 0]
    return {
        "businesses": len(rows),
        "mae_index": float(np.mean([row["mae"] for row in rows])),
        "positive_loan_businesses": len(eligible),
        "zero_loan_businesses": len(rows) - len(eligible),
        "mean_confidence": float(np.mean([row["confidence"] for row in rows])),
        "adaptive_capacity_coverage_pct": float(
            np.mean([row["adaptive_coverage"] for row in eligible])
        )
        if eligible
        else None,
        "equal_reference_capacity_coverage_pct": float(
            np.mean([row["equal_reference_coverage"] for row in eligible])
        )
        if eligible
        else None,
        "adaptive_overload_months": sum(row["adaptive_overloads"] for row in eligible),
        "annuity_overload_months": sum(row["equal_overloads"] for row in eligible),
        "adaptive_fewer_overloads_businesses_pct": percent(
            [row["adaptive_overloads"] < row["equal_overloads"] for row in eligible]
        ),
        "adaptive_same_overloads_businesses_pct": percent(
            [row["adaptive_overloads"] == row["equal_overloads"] for row in eligible]
        ),
        "adaptive_more_overloads_businesses_pct": percent(
            [row["adaptive_overloads"] > row["equal_overloads"] for row in eligible]
        ),
    }


def evaluate(model_path: str | Path) -> dict:
    model = ForecastModel.load(model_path)
    businesses = generate_split("test")
    test_ids = {business.business_id for business in businesses}
    assert len(test_ids) == TEST_COUNT
    assert not test_ids & set(model.selection["train_ids"])
    assert not test_ids & set(model.selection["validation_ids"])
    actual_parts, candidate_parts = (
        [],
        {name: [] for name in ("seasonal_naive", "gradient_boosting", "blend_50")},
    )
    rows, partial_actual, partial_predictions, inference_ms, serving_parts = (
        [],
        [],
        [],
        [],
        [],
    )
    transfer_parts = {
        weight: [] for weight in model.selection["transfer_validation_mae_index"]
    }
    weak_precision, strong_precision = [], []
    digest = hashlib.sha256()
    for business in businesses:
        request = business.request()
        history = aggregate(request)
        actual = business.future_net
        actual_parts.append(actual)
        digest.update(business.business_id.encode())
        digest.update(actual.astype("<f8").tobytes())
        for name, prediction in model.predict_candidates(history).items():
            candidate_parts[name].append(prediction)
        for weight, prediction in model.predict_transfer_candidates(history).items():
            transfer_parts[weight].append(prediction)
        started = time.perf_counter()
        response = score_request(request, model, "evaluation")
        inference_ms.append((time.perf_counter() - started) * 1000)
        forecast = np.asarray(response.seasonality.monthly_forecast_index)
        serving_parts.append(forecast)
        plan = capacity_plan(history, forecast)
        payments = plan["payments"]
        assert np.all(payments >= 0)
        assert np.all(payments <= plan["capacities"] + 1e-10)
        assert np.isclose(np.sum(payments), plan["principal"])
        equal_annuity = np.full(12, plan["principal"] / 12)
        rows.append(
            {
                "business_id": business.business_id,
                "cohort": business.cohort,
                "mae": float(np.mean(np.abs(actual - forecast))),
                "principal": plan["principal"],
                "confidence": response.confidence,
                "adaptive_coverage": float(np.mean(actual >= payments) * 100),
                "equal_reference_coverage": float(
                    np.mean(actual >= plan["equal_installment"]) * 100
                ),
                "adaptive_overloads": int(np.count_nonzero(payments > actual)),
                "equal_overloads": int(np.count_nonzero(equal_annuity > actual)),
                "flags": response.flags,
            }
        )
        actual_q25, actual_q75 = np.quantile(actual, [0.25, 0.75])
        months = [(history.forecast_start + offset) % 12 + 1 for offset in range(12)]
        for labels, cutoff, target in (
            (response.seasonality.weak_months, actual_q25, weak_precision),
            (response.seasonality.strong_months, actual_q75, strong_precision),
        ):
            for calendar_month in labels:
                actual_value = actual[months.index(calendar_month)]
                target.append(
                    bool(
                        actual_value < cutoff
                        if target is weak_precision
                        else actual_value > cutoff
                    )
                )
        # Same unseen businesses and future targets, with current-month partial
        # events censored. Report separately; never use for model selection.
        partial_payload = request.model_dump()
        partial_payload["as_of_date"] = request.as_of_date[:8] + "20"
        partial_payload["transactions"] = [
            row
            for row in partial_payload["transactions"]
            if row["ts"][:10] <= partial_payload["as_of_date"]
        ]
        partial_request = ScoreRequest.model_validate(partial_payload)
        partial_actual.append(actual)
        partial_predictions.append(model.predict(aggregate(partial_request)))
    candidate_metrics = {
        name: forecast_metrics(np.concatenate(actual_parts), np.concatenate(parts))
        for name, parts in candidate_parts.items()
    }
    endpoint_ms, status_counts, large_endpoint_ms, large_status_counts = [], {}, [], {}
    large_payload = businesses[0].request().model_dump()
    original_events = large_payload["transactions"]
    large_payload["transactions"] = [
        original_events[index % len(original_events)] for index in range(20000)
    ]
    large_body = json.dumps(large_payload).encode()
    with tempfile.TemporaryDirectory(prefix="wiut-ml-evaluation-") as directory:
        app = create_app(model_path, Path(directory) / "audit.jsonl")
        with TestClient(app) as client:
            # One warmup excluded from the measurement; audit fsync stays enabled.
            assert (
                client.post(
                    "/score", json=businesses[0].request().model_dump()
                ).status_code
                == 200
            )
            for business in businesses:
                started = time.perf_counter()
                reply = client.post("/score", json=business.request().model_dump())
                endpoint_ms.append((time.perf_counter() - started) * 1000)
                status_counts[str(reply.status_code)] = (
                    status_counts.get(str(reply.status_code), 0) + 1
                )
                if reply.status_code == 200:
                    ScoreResponse.model_validate(reply.json())
            for _ in range(5):
                started = time.perf_counter()
                reply = client.post(
                    "/score",
                    content=large_body,
                    headers={"content-type": "application/json"},
                )
                large_endpoint_ms.append((time.perf_counter() - started) * 1000)
                large_status_counts[str(reply.status_code)] = (
                    large_status_counts.get(str(reply.status_code), 0) + 1
                )
                if reply.status_code == 200:
                    ScoreResponse.model_validate(reply.json())
        audit_events = sum(1 for _ in (Path(directory) / "audit.jsonl").open())
    selection = {
        key: value for key, value in model.selection.items() if not key.endswith("_ids")
    }
    return {
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "model_version": model.version,
        "selection": selection,
        "test_protocol": {
            "businesses": TEST_COUNT,
            "future_months_per_business": 12,
            "business_disjoint": True,
            "test_used_for_selection": False,
            "future_actual_sha256": digest.hexdigest(),
            "capacity_and_schedule_population": "Only positive-principal businesses; zero-loan cohorts reported separately",
            "overload_definition": "payment > actual future net surplus; a zero payment in a negative-surplus month also counts",
            "annuity_comparator": "Same indexed principal, 12-month term and explicitly 0% APR; equal installments",
            "mape_policy": "Exclude abs(actual)<1 index. Negative actuals use absolute denominator. MAPE remains unstable near zero and is not the selection metric.",
        },
        "forecast_candidates": candidate_metrics,
        "transfer_candidates": {
            weight: forecast_metrics(
                np.concatenate(actual_parts), np.concatenate(parts)
            )
            for weight, parts in transfer_parts.items()
        },
        "selected_forecast": forecast_metrics(
            np.concatenate(actual_parts), np.concatenate(serving_parts)
        ),
        "partial_assessment_month_selected_forecast": forecast_metrics(
            np.concatenate(partial_actual), np.concatenate(partial_predictions)
        ),
        "capacity_schedule": summary(rows),
        "seasonality": {
            "weak_month_precision_pct": percent(weak_precision),
            "strong_month_precision_pct": percent(strong_precision),
            "ground_truth": "Future realised net-flow bottom/top quartiles, not generator seasonal parameters",
        },
        "cohorts": {
            cohort: summary([row for row in rows if row["cohort"] == cohort])
            for cohort in sorted({row["cohort"] for row in rows})
        },
        "latency": {
            "hardware": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "logical_cpus": os.cpu_count(),
            },
            "samples": len(businesses),
            "inference_median_ms": float(np.median(inference_ms)),
            "inference_p95_ms": float(np.quantile(inference_ms, 0.95)),
            "local_testclient_with_validation_and_fsync_median_ms": float(
                np.median(endpoint_ms)
            ),
            "local_testclient_with_validation_and_fsync_p95_ms": float(
                np.quantile(endpoint_ms, 0.95)
            ),
            "http_status_counts": status_counts,
            "audit_events": audit_events,
            "max_20000_transaction_request": {
                "samples": 5,
                "request_body_bytes": len(large_body),
                "median_ms": float(np.median(large_endpoint_ms)),
                "p95_ms": float(np.quantile(large_endpoint_ms, 0.95)),
                "http_status_counts": large_status_counts,
                "construction": "Repeated generated synthetic transaction events; latency-only, not a capacity accuracy test",
            },
            "scope": "Single process, warm model, sequential local TestClient. Includes JSON validation, response serialization and durable audit; excludes network/load and train/startup.",
        },
    }


def display(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def markdown(report: dict) -> str:
    selected = report["selection"]["selected_candidate"]
    capacity = report["capacity_schedule"]
    latency = report["latency"]
    lines = [
        "# Measured synthetic evaluation",
        "",
        f"Measured {report['measured_at_utc']}. Model `{report['model_version']}`.",
        "",
        "All results below were produced by `uv run python -m capacity_ml.evaluate` on generated future transactions. They are synthetic engineering measurements, not evidence of bank performance or default prediction.",
        "",
        "Public Uzbekistan SIAT 2020–2022 retail aggregates calibrate half the calendar component for four retail-like synthetic cohorts; later aggregate years are excluded from generator calibration. Every borrower transaction, expense and future net-flow target remains synthetic. An additional real-revenue component is trained directly from licensed aggregates and transferred only if synthetic validation MAE improves; its separate report measures actual public revenue forecasts, never borrower capacity.",
        "",
        f"Selection used 180 training businesses (complete/partial rolling origins) and 60 separate validation businesses. The selected candidate is **{selected}** by validation MAE. The held-out 120 test businesses are disjoint from both sets and each contributes 12 future actual months. Test metrics did not change model selection, buffers, score weights or schedule policy.",
        "",
        "| Candidate | Validation MAE (index) | Test MAE (index) | Test MAPE (%) | Test WAPE (%) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, metrics in report["forecast_candidates"].items():
        lines.append(
            f"| {name} | {report['selection']['validation_mae_index'][name]:.2f} | {metrics['mae_index']:.2f} | {display(metrics['mape_abs_actual_ge_1_pct'])} | {display(metrics['wape_pct'])} |"
        )
    lines.extend(
        [
            "",
            f"The real-revenue model minus separately synthetic-trained expenses is compared with the chosen synthetic net model at fixed weights 0/0.25/0.5/1. Validation selects public weight **{report['selection']['transfer_weight']}** and serving mode `{report['selection']['serving_mode']}`. This decision precedes the held-out results below; a zero weight explicitly rejects unsuitable transfer.",
            "",
            "| Public component weight | Synthetic validation MAE (index) | Held-out MAE (index) |",
            "| --- | ---: | ---: |",
        ]
    )
    for weight, values in report["transfer_candidates"].items():
        lines.append(
            f"| {weight} | {report['selection']['transfer_validation_mae_index'][weight]:.2f} | {values['mae_index']:.2f} |"
        )
    lines.extend(
        [
            "",
            f"MAPE excludes {report['selected_forecast']['mape_excluded_months']} months with absolute actual surplus below 1 index; negative actuals use an absolute denominator. Near-zero/negative net flow makes this percentage difficult to interpret. MAE is the selection metric; WAPE is also shown. No forecast intervals or calibrated confidence probabilities are claimed.",
            "",
            f"The selected model's separate partial-assessment-month test MAE is **{report['partial_assessment_month_selected_forecast']['mae_index']:.2f} indices**. Incomplete current-month events are excluded while the target remains the next 12 calendar months after assessment.",
            "",
            f"Positive indexed loans were recommended for **{capacity['positive_loan_businesses']}/{capacity['businesses']}** test businesses; zero-loan cases are excluded from the following repayment metrics to avoid a trivial zero-payment success rate. Adaptive capacity coverage is **{display(capacity['adaptive_capacity_coverage_pct'])}%** of those future business-months; coverage for the conservative 20th-percentile equal-installment reference is **{display(capacity['equal_reference_capacity_coverage_pct'])}%**.",
            "",
            f"For the same principal, 12-month term and explicit 0% APR, adaptive schedules produce **{capacity['adaptive_overload_months']} overload months** versus **{capacity['annuity_overload_months']}** for equal installments (the zero-interest annuity). **{display(capacity['adaptive_fewer_overloads_businesses_pct'])}%** of eligible businesses improve, **{display(capacity['adaptive_same_overloads_businesses_pct'])}%** tie and **{display(capacity['adaptive_more_overloads_businesses_pct'])}%** worsen. Overload means payment exceeds actual net surplus; zero payments in negative months count too. Forecast-based caps cannot guarantee future affordability.",
            "",
            f"The measured overload reduction (equal minus adaptive) is **{capacity['annuity_overload_months'] - capacity['adaptive_overload_months']} months** in this test; a negative value means adaptive is worse. It is not a consistent advantage for every business and must not be marketed as proven repayment improvement. Model and buffer settings remain fixed rather than being retuned on these test outcomes.",
            "",
            f"Weak/strong-month precision against future realised quartiles is **{display(report['seasonality']['weak_month_precision_pct'])}% / {display(report['seasonality']['strong_month_precision_pct'])}%**. Many forecast labels miss the realised quartiles. The evaluator never reads hidden generator seasonal parameters as labels.",
            "",
            "| Cohort | Businesses | MAE (index) | Loans | Mean confidence | Adaptive coverage (%) | Adaptive overloads | Equal overloads |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for cohort, metrics in report["cohorts"].items():
        lines.append(
            f"| {cohort} | {metrics['businesses']} | {metrics['mae_index']:.2f} | {metrics['positive_loan_businesses']} | {metrics['mean_confidence']:.3f} | {display(metrics['adaptive_capacity_coverage_pct'])} | {metrics['adaptive_overload_months']} | {metrics['annuity_overload_months']} |"
        )
    lines.extend(
        [
            "",
            "Known failures include short history, noisy high growth, unseen seasonal shapes and abrupt pattern breaks. The flags detect some observed changes; no flag can identify a future shock. Confidence is an evidence heuristic and must not be presented as calibrated certainty. Results for each difficult cohort are shown even where the model or adaptive schedule disappoints.",
            "",
            f"On `{latency['hardware']['platform']}` (`{latency['hardware']['machine']}`, {latency['hardware']['logical_cpus']} logical CPUs), {latency['samples']} sequential warm measurements gave inference median/P95 **{latency['inference_median_ms']:.2f}/{latency['inference_p95_ms']:.2f} ms**, and local `/score` TestClient median/P95 **{latency['local_testclient_with_validation_and_fsync_median_ms']:.2f}/{latency['local_testclient_with_validation_and_fsync_p95_ms']:.2f} ms** including JSON validation, response serialization and audit fsync. HTTP counts: `{latency['http_status_counts']}`. These exclude real network latency, concurrent load, training and startup; reruns change timings.",
            "",
            f"A separate five-request stress sample with the allowed maximum **20,000 synthetic transaction events** ({latency['max_20000_transaction_request']['request_body_bytes']} body bytes) measured median/P95 **{latency['max_20000_transaction_request']['median_ms']:.2f}/{latency['max_20000_transaction_request']['p95_ms']:.2f} ms**. Status counts: `{latency['max_20000_transaction_request']['http_status_counts']}`. The generated events are repeated for this latency-only check; this is not an additional accuracy sample.",
            "",
            "Local inference calls no external API and incurs no per-request provider fee. CPU, memory, storage, operational support and retraining still cost money; no monetary cost estimate was measured. The README lists deployment and validation limitations.",
            "",
            "[Machine-readable measured values](metrics.json)",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", default=os.environ.get("ML_MODEL_PATH", "runtime/model.joblib")
    )
    parser.add_argument("--output", default="reports")
    args = parser.parse_args()
    report = evaluate(args.model)
    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "metrics.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    (destination / "metrics.md").write_text(markdown(report))
    print(
        json.dumps(
            {
                "model_version": report["model_version"],
                "selected_forecast": report["selected_forecast"],
                "capacity_schedule": report["capacity_schedule"],
                "latency": report["latency"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
