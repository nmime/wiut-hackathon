"""Run the previously reported international real-revenue regression benchmark.

The reporting helpers never fit or select a model. Raw units are comparable only
within one provider; cross-provider comparisons use each history's own scale.
"""

import argparse
import hashlib
import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .forecasting import ForecastModel, normalizer, seasonal_forecast
from .public_revenue import PublicCase

BOOTSTRAP_SEED = 20261011
BOOTSTRAP_REPLICATES = 2000
MAX_PROVIDER_REGRESSION_PCT = 10.0
AUDIT_PROTOCOL_VERSION = (
    "international-region-v1:terminal-v1:macro-mae-positive:provider-loss10"
)


def validate_predictions(
    cases: list[PublicCase], predictions: list[np.ndarray]
) -> None:
    if not cases or len(cases) != len(predictions):
        raise ValueError("Evaluation requires nonempty aligned cases and predictions")
    for case, predicted in zip(cases, predictions, strict=True):
        actual = np.asarray(case.actual)
        predicted = np.asarray(predicted)
        if actual.ndim != 1 or actual.shape != predicted.shape or not len(actual):
            raise ValueError("Forecast and target arrays must have identical shapes")
        if np.any(~np.isfinite(actual)) or np.any(actual < 0):
            raise ValueError("Invalid real observations must be excluded, not clipped")
        if np.any(~np.isfinite(predicted)) or np.any(predicted < 0):
            raise ValueError("Real revenue predictions must be finite and nonnegative")


def forecast_metrics(
    cases: list[PublicCase], predictions: list[np.ndarray], *, same_units: bool = True
) -> dict:
    """Measure observed targets; MASE uses only history before each forecast."""
    validate_predictions(cases, predictions)
    actual = np.concatenate([case.actual for case in cases])
    predicted = np.concatenate(predictions)
    error = np.abs(actual - predicted)
    scales = np.concatenate(
        [np.full(len(case.actual), normalizer(case.history)) for case in cases]
    )
    case_mae = [
        float(np.mean(np.abs(case.actual - prediction)) / normalizer(case.history))
        for case, prediction in zip(cases, predictions, strict=True)
    ]
    denominator = np.abs(actual) + np.abs(predicted)
    smape = np.divide(
        200 * error,
        denominator,
        out=np.zeros_like(error),
        where=denominator > 0,
    )
    mase, missing_history, zero_denominator, mase_months = [], 0, 0, 0
    for case, prediction in zip(cases, predictions, strict=True):
        history = np.asarray(case.history.inflow)
        if len(history) < 13:
            missing_history += 1
            continue
        seasonal_scale = float(np.mean(np.abs(history[12:] - history[:-12])))
        if seasonal_scale <= 0:
            zero_denominator += 1
            continue
        mase.extend((np.abs(case.actual - prediction) / seasonal_scale).tolist())
        mase_months += len(case.actual)
    normalized_actual_sum = float(np.sum(actual / scales))
    actual_sum = float(np.sum(actual))
    return {
        "cases": len(cases),
        "series": len({case.identity for case in cases}),
        "entity_groups": len({case.group for case in cases}),
        "months": len(actual),
        "unique_target_observations": len(
            {
                (case.identity, case.history.forecast_start + horizon)
                for case in cases
                for horizon in range(len(case.actual))
            }
        ),
        "mae_provider_units": float(np.mean(error)) if same_units else None,
        "normalized_mae": float(np.mean(error / scales)),
        "macro_case_normalized_mae": float(np.mean(case_mae)),
        "smape_pct": float(np.mean(smape)),
        "smape_both_zero_months": int(np.count_nonzero(denominator == 0)),
        "seasonal_mase": float(np.mean(mase)) if mase else None,
        "mase_included_months": mase_months,
        "mase_excluded_short_history_cases": missing_history,
        "mase_excluded_zero_denominator_cases": zero_denominator,
        "wape_pct": float(np.sum(error) / actual_sum * 100)
        if same_units and actual_sum > 0
        else None,
        "normalized_wape_pct": float(
            np.sum(error / scales) / normalized_actual_sum * 100
        )
        if normalized_actual_sum > 0
        else None,
        "zero_actual_months": int(np.count_nonzero(actual == 0)),
        "wape_excluded_months": 0,
    }


def grouped_improvement_interval(
    cases: list[PublicCase],
    predictions: list[np.ndarray],
    baseline: list[np.ndarray],
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Bootstrap whole declared entity groups, preserving dependent windows."""
    validate_predictions(cases, predictions)
    validate_predictions(cases, baseline)
    if replicates < 1:
        raise ValueError("Bootstrap replication count must be positive")
    groups: dict[str, list[list[float]]] = defaultdict(list)
    for case, prediction, naive in zip(cases, predictions, baseline, strict=True):
        scale = normalizer(case.history)
        groups[case.group].append(
            [
                float(np.mean(np.abs(case.actual - prediction)) / scale),
                float(np.mean(np.abs(case.actual - naive)) / scale),
            ]
        )
    sums = np.asarray([np.sum(groups[group], axis=0) for group in sorted(groups)])
    total = np.sum(sums, axis=0)
    point = float((1 - total[0] / total[1]) * 100) if total[1] > 0 else None
    bounds = None
    usable = 0
    if len(sums) >= 2 and total[1] > 0:
        samples = np.random.default_rng(seed).integers(
            0, len(sums), size=(replicates, len(sums))
        )
        totals = np.sum(sums[samples], axis=1)
        valid = totals[:, 1] > 0
        usable = int(np.count_nonzero(valid))
        if usable:
            improvement = (1 - totals[valid, 0] / totals[valid, 1]) * 100
            bounds = np.quantile(improvement, [0.025, 0.975]).tolist()
    return {
        "macro_case_normalized_mae_improvement_pct": point,
        "grouped_bootstrap_95pct_interval": bounds,
        "resampling_groups": len(sums),
        "bootstrap_replicates": replicates,
        "usable_replicates": usable,
        "seed": seed,
        "interval_status": "estimated" if bounds is not None else "undefined",
        "interval_limit": "Entity groups may still share national economic shocks; percentile intervals are descriptive, not a guarantee of future performance.",
    }


def evaluate_cases(
    cases: list[PublicCase],
    predictions: list[np.ndarray],
    providers: dict[str, str],
) -> dict:
    """Report a single already selected forecast against one fixed baseline."""
    baseline = [
        np.maximum(seasonal_forecast(case.history), 0)[: len(case.actual)]
        for case in cases
    ]
    provider_names = {providers[case.identity] for case in cases}

    def slice_report(indices: list[int], *, same_units: bool = True) -> dict:
        selected_cases = [cases[index] for index in indices]
        selected_predictions = [predictions[index] for index in indices]
        selected_baseline = [baseline[index] for index in indices]
        return {
            "selected": forecast_metrics(
                selected_cases, selected_predictions, same_units=same_units
            ),
            "seasonal_naive": forecast_metrics(
                selected_cases, selected_baseline, same_units=same_units
            ),
            "improvement": grouped_improvement_interval(
                selected_cases, selected_predictions, selected_baseline
            ),
        }

    providers_report, sectors, histories = {}, {}, {}
    for provider in sorted(provider_names):
        indices = [
            index
            for index, case in enumerate(cases)
            if providers[case.identity] == provider
        ]
        providers_report[provider] = slice_report(indices)
    for sector in sorted({case.sector for case in cases}):
        indices = [index for index, case in enumerate(cases) if case.sector == sector]
        units = len({providers[cases[index].identity] for index in indices}) == 1
        sectors[sector] = slice_report(indices, same_units=units)
    for label, minimum, maximum in (
        ("cold_3_to_11_months", 3, 11),
        ("short_12_to_23_months", 12, 23),
        ("long_at_least_24_months", 24, None),
    ):
        indices = [
            index
            for index, case in enumerate(cases)
            if len(case.history.inflow) >= minimum
            and (maximum is None or len(case.history.inflow) <= maximum)
        ]
        if indices:
            units = len({providers[cases[index].identity] for index in indices}) == 1
            histories[label] = slice_report(indices, same_units=units)
    horizons = {}
    for horizon in range(max(len(case.actual) for case in cases)):
        indices = [
            index for index, case in enumerate(cases) if len(case.actual) > horizon
        ]
        errors, baseline_errors = [], []
        for index in indices:
            scale = normalizer(cases[index].history)
            actual = cases[index].actual[horizon]
            errors.append(abs(actual - predictions[index][horizon]) / scale)
            baseline_errors.append(abs(actual - baseline[index][horizon]) / scale)
        horizons[str(horizon + 1)] = {
            "cases": len(indices),
            "selected_normalized_mae": float(np.mean(errors)),
            "seasonal_naive_normalized_mae": float(np.mean(baseline_errors)),
        }
    return {
        "overall": slice_report(
            list(range(len(cases))), same_units=len(provider_names) == 1
        ),
        "providers": providers_report,
        "sectors": sectors,
        "history_length": histories,
        "forecast_horizon": horizons,
    }


def audit_acceptance(audit: dict) -> dict:
    """Predetermined MVP forecast guardrails, never a default-risk certificate."""
    point = audit["overall"]["improvement"]["macro_case_normalized_mae_improvement_pct"]
    provider_changes = {
        provider: values["improvement"]["macro_case_normalized_mae_improvement_pct"]
        for provider, values in audit["providers"].items()
    }
    passes = (
        point is not None
        and point > 0
        and all(
            change is not None and change >= -MAX_PROVIDER_REGRESSION_PCT
            for change in provider_changes.values()
        )
    )
    return {
        "status": "pass" if passes else "fail",
        "rules_frozen_before_final_evaluation": True,
        "overall_improvement_must_exceed_pct": 0.0,
        "maximum_provider_regression_pct": MAX_PROVIDER_REGRESSION_PCT,
        "measured_overall_improvement_pct": point,
        "measured_provider_improvements_pct": provider_changes,
        "policy": "Engineering guardrail: positive overall macro historical-scale-normalized MAE improvement against fixed seasonal naive, and no provider more than 10% worse. Cluster uncertainty is reported rather than hidden. This is not validation of individual borrowers, loan repayment, calibrated confidence or default risk.",
    }


def evaluate(model_path: str | Path) -> dict:
    # Imports stay local: formula tests do not need or read the real snapshots.
    from .international_data import (
        build_international_cases,
        load_international_series,
    )

    model = ForecastModel.load(model_path)
    series, metadata = load_international_series()
    public = model.public_revenue_model
    if public.metadata.get("international_data_sha256") != metadata["data_sha256"]:
        raise ValueError("International snapshot differs from the trained artifact")
    cases, exclusions = build_international_cases("test", dataset=(series, metadata))
    providers = {
        row.identity: row.source.get("provider", row.identity.split(":", 1)[0])
        for row in series
    }
    predictions = [public.predict(case.history)[: len(case.actual)] for case in cases]
    audit = evaluate_cases(cases, predictions, providers)
    exclusion_counts: dict[str, dict[str, int]] = {}
    for exclusion in exclusions:
        provider = exclusion["identity"].split(":", 1)[0]
        reasons = exclusion_counts.setdefault(provider, {})
        reason = exclusion["reason"]
        reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "model_version": model.version,
        "selected_real_revenue_candidate": public.selected,
        "audit_protocol": {
            "version": AUDIT_PROTOCOL_VERSION,
            "status": "legacy_regression_previously_reported",
            "geographic_time_protocol_frozen_pre_selection": all(
                protocol["frozen_before_training"]
                for protocol in metadata["protocols"].values()
            ),
            "training_source_sha256": model.selection["source_sha256"],
            "international_snapshot_sha256": metadata["data_sha256"],
            "evaluator_source_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "repeated_frozen_runs": "Reproduction of the same frozen model and protocol; not a new independent fresh evaluation",
        },
        "selection_metadata": public.metadata,
        "international_data": metadata,
        "excluded_final_windows": exclusions,
        "excluded_final_window_counts": exclusion_counts,
        "legacy_holdout": audit,
        "predetermined_acceptance": audit_acceptance(audit),
        "metric_policy": "Primary comparisons use historical-scale-normalized absolute error. Raw MAE and WAPE are computed within each provider's declared units only, never pooled across AUD/CAD. sMAPE assigns exactly zero error to actual=forecast=0; all other observations are included. Seasonal MASE divides by mean absolute 12-month differences in the input history only, with undefined short or constant histories reported. WAPE includes zero and near-zero months; an all-zero actual denominator is undefined.",
        "test_policy": "These ABS/Canada terminal labels were reported during the previous model upgrade, so this is now a legacy regression benchmark, not fresh confirmation. Labels remain excluded from fitting and validation selection. Fixed seasonal naive is the comparison. The separately reserved external-provider audit supplies new evidence.",
        "scope": "Licensed real aggregate revenue only. No real borrower expense, payment-capacity, repayment or default outcomes are available. This forecast evaluation does not validate lending decisions.",
        "limitations": "All sectors of a geography share an entity group. Related sectors and regions remain correlated through national economic shocks; clustered intervals from the small number of final geographies are descriptive. Time boundaries are provider-specific: other countries can have training observations later than an international test date, so this is not a globally chronological future holdout. Provider snapshots use one current revision vintage, not unrevised observations available at each historical date. International aggregate turnover can differ materially from an individual borrower's bank receipts.",
    }


def markdown(report: dict) -> str:
    audit = report["legacy_holdout"]
    overall = audit["overall"]
    improvement = overall["improvement"]

    def value(number: float | None) -> str:
        return "undefined" if number is None else f"{number:,.4f}"

    lines = [
        "# Legacy international real-revenue forecast regression",
        "",
        f"Measured {report['measured_at_utc']} with artifact `{report['model_version']}`; frozen real-revenue candidate: **{report['selected_real_revenue_candidate']}**. Reproduce with `uv run python -m capacity_ml.evaluate_international` after training the frozen artifact.",
        "",
        "These previously reported holdouts are now **legacy regression benchmarks**, not fresh confirmatory data. Model fitting and validation still exclude their labels. The [external-provider audit](external-metrics.md) supplies the new final check.",
        "",
        f"The final audit contains **{overall['selected']['series']} real series**, **{overall['selected']['entity_groups']} disjoint geographic split groups** and **{overall['selected']['months']:,} observed forecast months** ({overall['selected']['unique_target_observations']:,} unique targets). Excluded final-window counts by provider and reason: `{report['excluded_final_window_counts']}`; [all excluded identities and reasons](international-metrics.json) remain available. Groups are separated from model fitting and candidate validation; each provider's terminal test interval follows that provider's training and validation intervals. Other countries may have later training observations.",
        "",
        "| Forecast | Macro window normalized MAE | sMAPE (%) | Seasonal MASE | Normalized WAPE (%) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name in ("selected", "seasonal_naive"):
        metrics = overall[name]
        lines.append(
            f"| {name} | {value(metrics['macro_case_normalized_mae'])} | {value(metrics['smape_pct'])} | {value(metrics['seasonal_mase'])} | {value(metrics['normalized_wape_pct'])} |"
        )
    lines.extend(
        [
            "",
            f"Selected-model macro normalized MAE improvement versus fixed seasonal naive: **{value(improvement['macro_case_normalized_mae_improvement_pct'])}%**. A deterministic whole-geography bootstrap gives the descriptive 95% interval `{improvement['grouped_bootstrap_95pct_interval']}` percentage points from **{improvement['resampling_groups']} groups** ({improvement['usable_replicates']} usable replicates). Small group counts and correlated economic shocks limit this interval; it is not a future-accuracy guarantee.",
            "",
            "| Provider | Series | Months | Selected normalized MAE | Naive normalized MAE | Selected raw MAE (provider units) | Selected WAPE (%) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for provider, results in audit["providers"].items():
        selected, naive = results["selected"], results["seasonal_naive"]
        lines.append(
            f"| {provider} | {selected['series']} | {selected['months']} | {value(selected['macro_case_normalized_mae'])} | {value(naive['macro_case_normalized_mae'])} | {value(selected['mae_provider_units'])} | {value(selected['wape_pct'])} |"
        )
    lines.extend(
        [
            "",
            "Raw monetary errors are shown only within their original provider units. AUD and CAD errors are never pooled or converted to amount indices. Provider units, attribution, retrieval dates, snapshot hashes and fixed split dates are included in the machine-readable report.",
            "",
        ]
    )
    for source in report["international_data"]["sources"]:
        lines.append(
            f"- [{source['publisher']}: {source['title']}]({source['landing_url']}) — **{source['units']}**, [{source['license']}]({source['license_url']}). Retrieved {source['retrieved_utc']}; raw source SHA256 `{source['raw_sha256']}`."
        )
    for provider, protocol in report["international_data"]["protocols"].items():
        lines.append(
            f"- `{provider}`: training targets through {protocol['training_target_end']}; validation {protocol['validation_target_start']}–{protocol['validation_target_end']}; terminal final audit {protocol['test_target_start']}–{protocol['test_target_end']}. All leaf sector records from one state/province share a split."
        )
    lines.extend(
        [
            "",
            f"Predetermined engineering acceptance: **{report['predetermined_acceptance']['status'].upper()}**. Overall macro normalized MAE must improve versus seasonal naive and no provider may worsen more than {MAX_PROVIDER_REGRESSION_PCT:g}%. Measured provider improvements: `{report['predetermined_acceptance']['measured_provider_improvements_pct']}`. These guardrails were fixed before reading final labels; they do not certify lending or default predictions.",
            "",
            "| History length | Cases | Selected normalized MAE | Naive normalized MAE |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for label, results in audit["history_length"].items():
        selected, naive = results["selected"], results["seasonal_naive"]
        lines.append(
            f"| {label} | {selected['cases']} | {value(selected['macro_case_normalized_mae'])} | {value(naive['macro_case_normalized_mae'])} |"
        )
    lines.extend(
        [
            "",
            "Provider, sector and each 1–12-month forecast-horizon breakdowns are preserved in [the full machine-readable audit](international-metrics.json). Empty short-history slices are omitted rather than claimed as validated. Overlapping targets are counted separately as forecast tasks and explicitly deduplicated as observations.",
            "",
            report["metric_policy"],
            "",
            f"MASE in the selected forecast includes {overall['selected']['mase_included_months']} months, excluding {overall['selected']['mase_excluded_short_history_cases']} windows with fewer than 13 history months and {overall['selected']['mase_excluded_zero_denominator_cases']} windows with a zero seasonal denominator. WAPE excludes **zero months**; all-zero denominators are undefined. sMAPE has {overall['selected']['smape_both_zero_months']} exactly zero/zero forecast-target pairs, assigned zero error.",
            "",
            report["test_policy"],
            "",
            report["limitations"],
            "",
            report["scope"],
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
    (destination / "international-metrics.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    (destination / "international-metrics.md").write_text(markdown(report))
    print(json.dumps(report["legacy_holdout"]["overall"], indent=2, allow_nan=False))
    if report["predetermined_acceptance"]["status"] != "pass":
        raise SystemExit(
            "Frozen real-revenue forecast failed the published MVP audit guardrails; reports preserved"
        )


if __name__ == "__main__":
    main()
