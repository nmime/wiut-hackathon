"""Audit frozen revenue forecasts on new Eurostat countries and unseen UK ONS."""

import argparse
import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path

from .evaluate_fresh import (
    EXTERNAL_PROTOCOL_VERSION,
    external_acceptance,
    revenue_component_fingerprint,
)
from .evaluate_international import evaluate_cases
from .forecasting import ForecastModel, MonthlyHistory
from .public_revenue import PublicCase

REPRODUCTION_LOSS_ABSOLUTE_TOLERANCE = 1e-9


def validate_revenue_continuity(fingerprint: dict, lineage: dict) -> dict:
    original = lineage["revenue_component_fingerprint"]
    if (
        fingerprint["recipe_sha256"] != original["recipe_sha256"]
        or fingerprint["selected_candidate"] != original["selected_candidate"]
    ):
        raise ValueError(
            "Revenue recipe differs from the audited v2 component; "
            "consumed external labels cannot qualify a changed predictor"
        )
    return {
        "recipe_match": True,
        "fitted_fingerprint_exact_match": fingerprint["sha256"] == original["sha256"],
        "original_revenue_component_sha256": original["sha256"],
        "scope": "Exact local fitted equality is recorded separately from a pinned-recipe cross-platform reproduction. Any fitted-byte difference also requires actual consumed-audit loss equality within 1e-9 absolute tolerance. These are reproducibility checks, never fresh model selection.",
    }


def validate_reproduced_losses(audit: dict, original: dict) -> dict:
    changes = {}

    def compare(name: str, current: dict, previous: dict) -> None:
        for metric in (
            "macro_case_normalized_mae",
            "normalized_mae",
            "smape_pct",
            "normalized_wape_pct",
            "mae_provider_units",
            "wape_pct",
        ):
            now, old = current.get(metric), previous.get(metric)
            if now is None or old is None:
                if now != old:
                    changes[f"{name}.{metric}"] = "undefined status changed"
            elif not math.isclose(
                now, old, rel_tol=0, abs_tol=REPRODUCTION_LOSS_ABSOLUTE_TOLERANCE
            ):
                changes[f"{name}.{metric}"] = now - old
        for count in (
            "series",
            "months",
            "unique_target_observations",
            "entity_groups",
        ):
            if current[count] != previous[count]:
                changes[f"{name}.{count}"] = current[count] - previous[count]

    compare("overall", audit["overall"]["selected"], original["overall"]["selected"])
    if set(audit["providers"]) != set(original["providers"]):
        changes["providers"] = "provider identities changed"
    for provider in set(audit["providers"]) & set(original["providers"]):
        compare(
            provider,
            audit["providers"][provider]["selected"],
            original["providers"][provider]["selected"],
        )
    return {
        "status": "pass" if not changes else "fail",
        "absolute_loss_tolerance": REPRODUCTION_LOSS_ABSOLUTE_TOLERANCE,
        "relative_loss_tolerance": 0,
        "out_of_tolerance_differences": changes,
        "scope": "Same frozen recipe/candidate with reproduced primary overall and provider losses/counts. This certifies metric reproduction at stated precision, not pointwise identical forecasts or new untouched labels.",
    }


def validate_external_isolation(public_metadata: dict, metadata: dict) -> None:
    if public_metadata.get("external_data_sha256") != metadata["data_sha256"]:
        raise ValueError("External source snapshot differs from the trained artifact")
    # ONS is the entire unseen provider; it supplies zero training/validation
    # rows. The source identifier is fixed before any audit values are read.
    for provider in ("ons", "uk_ons"):
        count = (
            public_metadata.get("training_by_provider", {})
            .get(provider, {})
            .get("examples", 0)
        )
        if count:
            raise ValueError(
                "Reserved whole-provider ONS observations entered training"
            )
        for candidate in public_metadata.get("combined_validation", {}).values():
            if provider in candidate.get("by_provider", {}):
                raise ValueError(
                    "Reserved whole-provider ONS observations entered selection"
                )


def evaluate(model_path: str | Path) -> dict:
    from .external_data import build_external_cases, load_external_series

    model = ForecastModel.load(model_path)
    series, metadata = load_external_series()
    public = model.public_revenue_model
    validate_external_isolation(public.metadata, metadata)
    fingerprint = revenue_component_fingerprint(model)
    lineage_path = (
        Path(__file__).parents[1].joinpath("reports/external-audit-v2-lineage.json")
    )
    lineage = json.loads(lineage_path.read_text())
    continuity = validate_revenue_continuity(fingerprint, lineage)
    original_report = json.loads(
        lineage_path.with_name("external-audit-v2-frozen.json").read_text()
    )
    cases, exclusions = build_external_cases("audit", dataset=(series, metadata))
    providers = {row.identity: row.source["provider"] for row in series}
    predictions = [public.predict(case.history)[: len(case.actual)] for case in cases]
    audit = evaluate_cases(cases, predictions, providers)
    reproduced = validate_reproduced_losses(audit, original_report["primary_audit"])
    stress = {}
    for history_months in (3, 6, 12):
        short_cases = [
            PublicCase(
                case.identity,
                case.sector,
                case.group,
                MonthlyHistory(
                    case.history.months[-history_months:],
                    case.history.inflow[-history_months:],
                    case.history.outflow[-history_months:],
                    case.history.forecast_start,
                ),
                case.actual,
            )
            for case in cases
        ]
        short_predictions = [
            public.predict(case.history)[: len(case.actual)] for case in short_cases
        ]
        stress[str(history_months)] = evaluate_cases(
            short_cases, short_predictions, providers
        )
    counts = {}
    for exclusion in exclusions:
        provider = exclusion["identity"].split(":", 1)[0]
        reasons = counts.setdefault(provider, {})
        reason = exclusion["reason"]
        reasons[reason] = reasons.get(reason, 0) + 1
    expected_providers = {source["provider"] for source in metadata["sources"]}
    acceptance = external_acceptance(audit, expected_providers)
    acceptance["unchanged_component_reproduction"] = reproduced["status"]
    if reproduced["status"] != "pass":
        acceptance["status"] = "fail"
    return {
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "model_version": model.version,
        "evaluation_status": "consumed_v2_external_regression_reproduction_unchanged_revenue_component",
        "protocol_version": EXTERNAL_PROTOCOL_VERSION,
        "revenue_component_fingerprint": fingerprint,
        "original_external_audit_lineage": lineage,
        "revenue_continuity": continuity,
        "reproduced_losses": reproduced,
        "source_sha256": model.selection["source_sha256"],
        "external_snapshot_sha256": metadata["data_sha256"],
        "evaluator_source_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "formula_source_sha256": {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in ("evaluate_fresh.py", "evaluate_international.py")
        },
        "frozen_protocol_document_sha256": hashlib.sha256(
            Path(__file__).parents[1].joinpath("data/audit-protocol-v2.md").read_bytes()
        ).hexdigest(),
        "selected_real_revenue_candidate": public.selected,
        "selection_metadata": public.metadata,
        "external_sources": metadata,
        "whole_provider_held_out": "UK ONS, no training or selection rows",
        "excluded_audit_windows": exclusions,
        "excluded_audit_counts": counts,
        "primary_audit": audit,
        "short_history_supplementary_stress": stress,
        "short_history_policy": "The same observed final targets are reused with only 3/6/12 historical months supplied. This is a stress slice, not more independent real observations, and does not choose or qualify the frozen candidate.",
        "predetermined_acceptance": acceptance,
        "source_selection_policy": "Whole-US Census MRTS was inaccessible without an API key; FRED workaround terms disallowed ML use. These sources were excluded before reading audit observations. The wholly unseen UK ONS source substituted solely for access/licensing; no source was selected on model errors.",
        "limitations": "Original aggregate nominal turnover/value indices are observed real revenues normalized to each publisher's base year, not borrower bank receipts or monetary values. Raw index points cannot be pooled across provider bases. Whole-country clusters retain within-country sector and economic-shock dependence. Seven intended audit countries provide limited descriptive uncertainty; current revision vintages are not an unrevised historical backtest. Dates are provider-local, since older-country training observations may follow an audit date. No real expense, repayment, capacity or default labels are present.",
        "freshness_policy": "The first v2 external audit was performed before inspecting its labels and is preserved as external-audit-v2-frozen.json/.md. This run is a regression reproduction of consumed labels: the pinned revenue recipe and selected candidate must match before case construction, local exact fitted equality is recorded, and reproduced overall/provider losses must match within 1e-9 absolute tolerance. Cross-platform same-recipe builds need not have identical learned bytes; this reports metric equality at stated precision, not pointwise identical predictions. Changing only net blend/expense/scoring does not make the revenue audit fresh again. No fitting/selection occurs here; a changed revenue recipe requires new reserved external targets.",
    }


def markdown(report: dict) -> str:
    audit = report["primary_audit"]
    selected, baseline = (
        audit["overall"]["selected"],
        audit["overall"]["seasonal_naive"],
    )
    improvement = audit["overall"]["improvement"]
    improvement_value = improvement["macro_case_normalized_mae_improvement_pct"]
    improvement_text = (
        "undefined (zero baseline error)"
        if improvement_value is None
        else f"{improvement_value:.4f}%"
    )
    acceptance = report["predetermined_acceptance"]
    lines = [
        "# External real-revenue audit",
        "",
        f"Measured {report['measured_at_utc']} with frozen model `{report['model_version']}` and real-revenue candidate **{report['selected_real_revenue_candidate']}**. Reproduce with `uv run python -m capacity_ml.evaluate_external`.",
        "",
        f"Report status: `{report['evaluation_status']}`. The initial untouched v2 result is preserved in [external-audit-v2-frozen.json](external-audit-v2-frozen.json). Repeated runs are consumed-label regression checks, not new independent evidence.",
        "",
        f"The original frozen cohort covers **{selected['series']} actual series / {selected['months']:,} observed future months**, representing {selected['unique_target_observations']:,} unique targets in **{selected['entity_groups']} country clusters**. Six reserved Eurostat countries and the wholly unseen UK ONS provider are separated from fitting and selection. Eurostat audit Sep 2025–Aug 2026; UK ONS Sep 2025–Aug 2026. Quality exclusions by provider/reason: `{report['excluded_audit_counts']}`; full identities are retained in [JSON](external-metrics.json).",
        "",
        "| Forecast | Macro normalized MAE | sMAPE (%) | Normalized WAPE (%) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, values in (("Frozen selected", selected), ("Seasonal naive", baseline)):
        wape = values["normalized_wape_pct"]
        lines.append(
            f"| {name} | {values['macro_case_normalized_mae']:.4f} | {values['smape_pct']:.4f} | {'undefined' if wape is None else f'{wape:.4f}'} |"
        )
    lines.extend(
        [
            "",
            f"Measured macro normalized MAE improvement: **{improvement_text}**; whole-country bootstrap descriptive 95% interval `{improvement['grouped_bootstrap_95pct_interval']}` percentage points. Resampling keeps each country's dependent sector records together. This small, correlated set cannot establish general or borrower-level accuracy.",
            "",
            f"Predetermined engineering acceptance: **{acceptance['status'].upper()}**. Overall normalized MAE must improve (>0%) versus seasonal naive and no provider may regress by more than 10%. Missing reserved providers fail rather than silently disappear. Actual provider improvements: `{acceptance['measured_provider_improvements_pct']}`; missing providers: `{acceptance['missing_expected_providers']}`.",
            "",
            "| Provider | Actual series | Future months | Selected normalized MAE | Naive normalized MAE | Selected raw MAE (provider index points) |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for provider, values in audit["providers"].items():
        selected, baseline = values["selected"], values["seasonal_naive"]
        lines.append(
            f"| {provider} | {selected['series']} | {selected['months']} | {selected['macro_case_normalized_mae']:.4f} | {baseline['macro_case_normalized_mae']:.4f} | {selected['mae_provider_units']:.4f} |"
        )
    lines.append("")
    for source in report["external_sources"]["sources"]:
        source_url = (
            source.get("landing_url") or source.get("source_url") or source["url"]
        )
        lines.append(
            f"- [{source.get('publisher', source['provider'])}: {source.get('title', source['provider'])}]({source_url}) — **{source['units']}**; [{source['license']}]({source['license_url']}); raw SHA256 `{source['raw_sha256']}`."
        )
    lines.extend(
        [
            "",
            "Raw nominal index-point errors remain within each provider and base year; only historical-scale-normalized errors pool sources. WAPE excludes no zero or near-zero months; sMAPE assigns zero error to exactly-zero actual/forecast pairs. Seasonal MASE uses input-history twelve-month differences only, with undefined short/zero denominators reported in JSON.",
            "",
            "| Historical months supplied (stress only) | Selected normalized MAE | Naive normalized MAE |",
            "| --- | ---: | ---: |",
        ]
    )
    for months, values in report["short_history_supplementary_stress"].items():
        lines.append(
            f"| {months} | {values['overall']['selected']['macro_case_normalized_mae']:.4f} | {values['overall']['seasonal_naive']['macro_case_normalized_mae']:.4f} |"
        )
    lines.extend(
        [
            "",
            report["short_history_policy"],
            "",
            report["source_selection_policy"],
            "",
            report["limitations"],
            "",
            report["freshness_policy"],
            "",
        ]
    )
    if report.get("presentation_only_clarification"):
        lines.extend([report["presentation_only_clarification"], ""])
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
    (destination / "external-metrics.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    (destination / "external-metrics.md").write_text(markdown(report))
    print(json.dumps(report["predetermined_acceptance"], indent=2, allow_nan=False))
    if report["predetermined_acceptance"]["status"] != "pass":
        raise SystemExit(
            "Frozen revenue forecast failed new external audit; reports preserved"
        )


if __name__ == "__main__":
    main()
