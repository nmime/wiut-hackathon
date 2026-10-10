"""Run the previously reported Uzbekistan revenue regression benchmark."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .forecasting import ForecastModel
from .public_revenue import build_cases, measure
from .revenue_data import load_revenue_series


def evaluate(model_path: str | Path) -> dict:
    artifact = ForecastModel.load(model_path)
    model = artifact.public_revenue_model
    series, metadata = load_revenue_series()
    if model.metadata["data_sha256"] != metadata["data_sha256"]:
        raise ValueError("Public revenue snapshot differs from the trained artifact")
    cases, exclusions = build_cases(series, metadata)
    tests = {}
    for split in ("test_2025", "test_2026"):
        tests[split] = {
            "candidates": measure(model, cases[split]),
            "selected_candidate": model.selected,
            "selected_by_sector": {
                sector: measure(
                    model, [case for case in cases[split] if case.sector == sector]
                )[model.selected]
                for sector in sorted({case.sector for case in cases[split]})
            },
            "valid_series": len({case.identity for case in cases[split]}),
            "excluded_windows": exclusions[split],
        }
    return {
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "model_version": artifact.version,
        "evaluation_status": "legacy_regression_benchmark_previously_reported",
        "public_training": model.metadata,
        "serving_transfer_weight": artifact.transfer_weight,
        "serving_mode": artifact.selection["serving_mode"],
        "synthetic_transfer_validation_mae_index": artifact.selection[
            "transfer_validation_mae_index"
        ],
        "tests": tests,
        "valid_cases_by_sector": {
            split: {
                sector: sum(case.sector == sector for case in rows)
                for sector in sorted({row.sector for row in series})
            }
            for split, rows in cases.items()
        },
        "metric_policy": "MAE in declared million UZS is for real aggregates only; normalized MAE divides each window by its positive historical mean so districts, regions and sectors share a scale. MAPE excludes zero actuals and is unstable near zero; neither test metric selects the model.",
        "scope": "Actual licensed revenue/service volume; no real borrower expenses, capacity, repayment or default labels. The original 2020–22/2023/2024–25 retail temporal benchmark remains separate and unchanged.",
        "vintage_caveat": "A single current provider vintage may revise older observations. Target-date boundaries are enforced, but this is not a backtest with historical unrevised vintages. The service definition changed in September 2024; only October 2024 onward is used, excluding the incomparable September increment.",
    }


def display(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.3f}"


def markdown(report: dict) -> str:
    public = report["public_training"]
    uzbekistan = public["training_by_provider"]["uzbekistan_siat"]
    lines = [
        "# Uzbekistan public-revenue regression benchmark",
        "",
        f"Measured {report['measured_at_utc']}; artifact `{report['model_version']}`. Reproduce with `uv run python -m capacity_ml.train` and `uv run python -m capacity_ml.evaluate_revenue`.",
        "",
        "These fixed Uzbekistan evaluation periods were reported before this model upgrade. They are now **legacy regression benchmarks**, not fresh confirmatory holdouts. Targets remain excluded from fitting and validation selection. See the [external-provider audit](external-metrics.md) for separately reserved final observations. The international evaluation is now also a previously reported regression benchmark.",
        "",
        f"The offline corpus contains **{public['published_observations']:,} published monthly observations** across retail, wholesale, district market services and accommodation/food service aggregates. Excluding national and parent totals, then respecting the service methodology boundary, leaves **{public['eligible_series']} eligible series / {public['eligible_observations_after_regime_filter']:,} observations**. These counts include retained source revisions; invalid forecasting windows are excluded rather than corrected or clipped.",
        "",
        f"The Uzbekistan portion supplies **{uzbekistan['cases']} rolling windows / {uzbekistan['examples']:,} actual target-month examples** from **{uzbekistan['series']} series**, representing **{uzbekistan['unique_target_observations']:,} unique target observations**. The combined Uzbekistan/Australia/Canada/Eurostat model uses **{public['training_examples']:,} actual target examples**; overlapping windows are not independent records. Uzbekistan targets end by December 2025. Regions are partitioned by a fixed hash into 8 training, 3 validation and 3 legacy test groups; all sectors/districts of a region stay together. Pre-2025 retail/wholesale histories are capped at 48 months. Post-break service histories before January 2025 contain only 3 months and are a cold-history limitation.",
        "",
        f"Uzbekistan development validation covers January–December 2025 in independent geographic groups. The combined model selects **{public['selected_candidate']}** by provider-balanced macro normalized validation MAE, giving each provider equal weight. The table below shows only the Uzbekistan validation slice, which may prefer a different candidate. Test targets remain excluded from fitting and selection. Source-revision exclusions: `{public['exclusions']}`. The 2025 legacy evaluation is an entity holdout; the 2026 evaluation also follows Uzbekistan training in time. Only January–August 2026 is published: the last four forecast months are unobserved and excluded.",
        "",
        f"Valid-window composition: `{report['valid_cases_by_sector']}`. In particular, source revisions exclude wholesale from validation and the 2025 holdout; its one 2026 case cannot establish sector-wide performance. The geographic validation group is small and uneven after exclusions.",
        "",
        "| Candidate | Validation normalized MAE | Validation MAE (million UZS) | Validation MAPE (%) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, values in public["uzbekistan_validation"].items():
        lines.append(
            f"| {name} | {display(values['normalized_mae'])} | {display(values['mae_million_uzs'])} | {display(values['mape_positive_actual_pct'])} |"
        )
    for split, test in report["tests"].items():
        lines.extend(
            [
                "",
                f"## {split.replace('_', ' ')}",
                "",
                f"Valid series: {test['valid_series']}; excluded complete windows: {test['excluded_windows']}. Candidates below are reported after validation selection is fixed.",
                "",
                "| Candidate | Months | Normalized MAE | MAE (million UZS) | MAPE (%) | WAPE (%) |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for name, values in test["candidates"].items():
            lines.append(
                f"| {name} | {values['months']} | {display(values['normalized_mae'])} | {display(values['mae_million_uzs'])} | {display(values['mape_positive_actual_pct'])} | {display(values['wape_pct'])} |"
            )
        lines.extend(
            [
                "",
                "| Selected-model sector | Cases | Months | Normalized MAE | MAE (million UZS) | MAPE (%) |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for sector, values in test["selected_by_sector"].items():
            lines.append(
                f"| {sector} | {values['cases']} | {values['months']} | {display(values['normalized_mae'])} | {display(values['mae_million_uzs'])} | {display(values['mape_positive_actual_pct'])} |"
            )
        selected = test["candidates"][test["selected_candidate"]]
        lines.extend(
            [
                "",
                f"MAPE excludes **{selected['mape_excluded_zero_months']} zero-actual months**. Near-zero positive values remain included, so percentage errors can be large even when aggregate WAPE improves.",
            ]
        )
    lines.extend(
        [
            "",
            "## Service transfer and limits",
            "",
            "Raw MAE is dominated by large regions; normalized errors, percentage metrics and all sector slices are shown above. Three-month post-break histories, near-zero actuals and provider revisions can produce large errors, especially for food services. These previously examined benchmark results are regression evidence; the external-provider final audit supplies the new accuracy check.",
            "",
            f"The real revenue model and borrower expense projection form a net-flow candidate. Expenses use either a separately synthetic-trained model or a nonnegative cost regression fitted to the borrower's observed past transactions; public revenue supplies no expense labels. Fixed weights 0/0.1/0.25/0.5/1 are compared on the 60 synthetic validation businesses with normalized-error checks; selected real-component weight: **{report['serving_transfer_weight']}**. Validation MAEs (indices): `{report['synthetic_transfer_validation_mae_index']}`. Serving mode: `{report['serving_mode']}`. A zero weight rejects unsuitable transfer. [Synthetic borrower regression evaluation](metrics.md) measures the actual serving model.",
            "",
            report["metric_policy"],
            "",
            report["vintage_caveat"],
            "",
            public["limitations"],
            "",
            "All source data below are published by Uzbekistan's National Statistics Committee under **CC BY 4.0**. The committed snapshot declares raw source hashes, retrieval and modification dates, official units and methodology notes. Monthly increments difference year-to-date totals within each year; January resets. Published service billions are explicitly multiplied by 1000 to obtain million UZS in this benchmark. Borrower inference normalizes patterns and rescales by the supplied amount-index mean; this does **not** declare an index-to-UZS conversion.",
            "",
        ]
    )
    for source in public["sources"]:
        if source.get("provider") in {"abs", "statcan", "eurostat", "ons"}:
            continue  # International/external units and licenses have own reports.
        lines.append(
            f"- [{source.get('title', source.get('indicator', 'Retail trade volume'))}]({source['landing_url']}) — [CC BY 4.0]({source['license_url']}); provider units: {source.get('units_as_published', 'million UZS')}."
        )
    lines.extend(
        ["", report["scope"], "", "[Machine-readable report](revenue-metrics.json)", ""]
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
    (destination / "revenue-metrics.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    (destination / "revenue-metrics.md").write_text(markdown(report))
    print(
        json.dumps(
            {
                split: test["candidates"][test["selected_candidate"]]
                for split, test in report["tests"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
