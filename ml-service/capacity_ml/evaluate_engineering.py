"""Measure one frozen serving model on a new synthetic engineering cohort."""

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .evaluate_fresh import (
    ORIGINAL_TARGET_ABSOLUTE_TOLERANCE,
    PROTOCOL_VERSION,
    engineering_audit,
    revenue_component_fingerprint,
    synthetic_component_fingerprint,
)
from .forecasting import ForecastModel

NORMALIZED_REPRODUCTION_TOLERANCE = 1e-9
INDEX_REPRODUCTION_TOLERANCE = 1e-6
PERCENT_REPRODUCTION_TOLERANCE = 1e-6


def validate_target_manifest(
    manifest: dict, original: dict, archive_digest: str
) -> None:
    """Verify the stored target floats exactly recover the first V5 hashes."""
    if (
        manifest["source_sha256"] != original["source_sha256"]
        or manifest["protocol_version"] != original["audit_protocol_version"]
        or manifest["original_report_sha256"] != archive_digest
        or manifest["pointwise_absolute_target_tolerance"]
        != ORIGINAL_TARGET_ABSOLUTE_TOLERANCE
        or manifest["pointwise_relative_target_tolerance"] != 0
    ):
        raise ValueError("Consumed original target manifest provenance changed")
    start, end = original["protocol"]["positions_inclusive"]
    cases = manifest["cases"]
    if [case["position"] for case in cases] != list(range(start, end + 1)):
        raise ValueError("Consumed target manifest positions/count changed")
    ids, target_hash, cohorts = [], hashlib.sha256(), Counter()
    for case in cases:
        values = np.asarray(case["future_net"], dtype=np.float64)
        months = np.asarray(case["forecast_month_ids"])
        if (
            values.shape != (12,)
            or np.any(~np.isfinite(values))
            or months.shape != (12,)
            or not np.issubdtype(months.dtype, np.integer)
            or not np.all(np.diff(months) == 1)
        ):
            raise ValueError("Consumed target manifest point/month schema changed")
        ids.append(case["business_id"])
        target_hash.update(case["business_id"].encode())
        target_hash.update(values.astype("<f8").tobytes())
        cohorts[case["cohort"]] += 1
    ids_hash = hashlib.sha256("\n".join(ids).encode()).hexdigest()
    if (
        len(set(ids)) != len(ids)
        or len(ids) != original["protocol"]["businesses"]
        or ids_hash != manifest["original_ids_sha256"]
        or ids_hash != original["protocol"]["ids_sha256"]
        or target_hash.hexdigest() != manifest["original_future_net_sha256"]
        or target_hash.hexdigest() != original["protocol"]["future_net_sha256"]
        or cohorts
        != {
            name: row["selected"]["businesses"]
            for name, row in original["cohorts"].items()
        }
    ):
        raise ValueError("Consumed original target manifest hashes/counts changed")


def validate_engineering_continuity(current: dict, original: dict) -> dict:
    """Reject a changed pipeline before reconstructing consumed V5 targets."""
    for field in (
        "model_version",
        "source_sha256",
        "audit_protocol_version",
        "frozen_protocol_document_sha256",
        "candidate_addendum_document_sha256",
        "serving_policy",
    ):
        if current[field] != original[field]:
            raise ValueError(
                f"Engineering V5 continuity changed: {field}; "
                "consumed labels cannot qualify a revised serving pipeline"
            )
    for component in (
        "synthetic_comparator_fingerprint",
        "revenue_component_fingerprint",
    ):
        if current[component]["recipe_sha256"] != original[component]["recipe_sha256"]:
            raise ValueError(f"Engineering V5 continuity changed: {component} recipe")
    return {
        "source_and_policy_match": True,
        "recipe_match": True,
        "local_synthetic_fitted_fingerprint_exact_match": current[
            "synthetic_comparator_fingerprint"
        ]["sha256"]
        == original["synthetic_comparator_fingerprint"]["sha256"],
        "local_revenue_fitted_fingerprint_exact_match": current[
            "revenue_component_fingerprint"
        ]["sha256"]
        == original["revenue_component_fingerprint"]["sha256"],
        "scope": "Same pipeline source, policies, protocol, candidate addendum and component recipes are required before target reconstruction. Learned bytes may differ across platforms; pointwise original-target continuity and exact identity/count/scoring invariants are always required afterward. Same-local fitted models require strict losses; portable fitted variants must independently pass all unchanged engineering gates while exposing strict-loss deltas/failures. This is consumed-label regression evidence, never a new audit.",
    }


def validate_reproduced_engineering(audit: dict, original: dict) -> dict:
    """Require identical cohort identities/targets and practically equal losses."""
    changes, invariant_changes, metric_deltas = {}, {}, {}

    def exact(path: str, now: object, previous: object) -> None:
        if now != previous:
            changes[path] = "identity, count or invariant changed"
            invariant_changes[path] = changes[path]

    def number(path: str, now: object, previous: object, tolerance: float) -> None:
        if now is None or previous is None:
            if now != previous:
                changes[path] = "undefined status changed"
        else:
            metric_deltas[path] = now - previous
            if not math.isclose(now, previous, rel_tol=0, abs_tol=tolerance):
                changes[path] = now - previous

    def metrics(path: str, now: dict, previous: dict) -> None:
        for field in (
            "businesses",
            "observed_future_months",
            "wape_excluded_zero_or_nearzero_months",
        ):
            exact(f"{path}.{field}", now[field], previous[field])
        for field, tolerance in (
            ("mae_index", INDEX_REPRODUCTION_TOLERANCE),
            ("macro_business_normalized_mae", NORMALIZED_REPRODUCTION_TOLERANCE),
            ("absolute_net_wape_pct", PERCENT_REPRODUCTION_TOLERANCE),
        ):
            number(f"{path}.{field}", now[field], previous[field], tolerance)

    def comparison(path: str, now: dict, previous: dict) -> None:
        for field in ("selected", "fixed_synthetic_reference"):
            metrics(f"{path}.{field}", now[field], previous[field])
        improvement, old_improvement = now["improvement"], previous["improvement"]
        number(
            f"{path}.improvement",
            improvement["macro_normalized_mae_improvement_pct"],
            old_improvement["macro_normalized_mae_improvement_pct"],
            PERCENT_REPRODUCTION_TOLERANCE,
        )
        interval, old_interval = (
            improvement["business_bootstrap_95pct_interval"],
            old_improvement["business_bootstrap_95pct_interval"],
        )
        if interval is None or old_interval is None:
            exact(f"{path}.interval", interval, old_interval)
        else:
            for index in range(2):
                number(
                    f"{path}.interval.{index}",
                    interval[index],
                    old_interval[index],
                    PERCENT_REPRODUCTION_TOLERANCE,
                )
        for field in (
            "independent_generated_business_seeds",
            "replicates",
            "usable_replicates",
            "seed",
        ):
            exact(f"{path}.{field}", improvement[field], old_improvement[field])

    comparison("overall", audit, original)
    for slice_name in ("cohorts", "history_length"):
        exact(
            f"{slice_name}.identities",
            set(audit[slice_name]),
            set(original[slice_name]),
        )
        for identity in set(audit[slice_name]) & set(original[slice_name]):
            comparison(
                f"{slice_name}.{identity}",
                audit[slice_name][identity],
                original[slice_name][identity],
            )
    exact("protocol", audit["protocol"], original["protocol"])
    exact("scoring_flow", audit["scoring_flow"], original["scoring_flow"])
    exact(
        "selected_uses_real_trained_estimator",
        audit["selected_uses_real_trained_estimator"],
        original["selected_uses_real_trained_estimator"],
    )
    exact(
        "predetermined_acceptance",
        audit["predetermined_acceptance"],
        original["predetermined_acceptance"],
    )
    for field in ("mean", "minimum", "maximum"):
        number(
            f"effective_real_weight.{field}",
            audit["effective_real_weight"][field],
            original["effective_real_weight"][field],
            1e-12,
        )
        if f"effective_real_weight.{field}" in changes:
            invariant_changes[f"effective_real_weight.{field}"] = changes[
                f"effective_real_weight.{field}"
            ]
    exact(
        "effective_real_weight.businesses_at_least_half",
        audit["effective_real_weight"]["businesses_at_least_half"],
        original["effective_real_weight"]["businesses_at_least_half"],
    )
    return {
        "status": "pass" if not changes else "fail",
        "exact_invariant_status": "pass" if not invariant_changes else "fail",
        "normalized_mae_absolute_tolerance": NORMALIZED_REPRODUCTION_TOLERANCE,
        "indexed_mae_absolute_tolerance": INDEX_REPRODUCTION_TOLERANCE,
        "percentage_and_interval_absolute_tolerance": PERCENT_REPRODUCTION_TOLERANCE,
        "effective_weight_absolute_tolerance": 1e-12,
        "relative_tolerance": 0,
        "out_of_tolerance_differences": changes,
        "measured_metric_deltas_from_first_mac_result": metric_deltas,
        "invariant_differences": invariant_changes,
        "scope": "Strict loss reproduction checks primary, cohort and history-slice errors and bootstrap summaries at declared precision. Business IDs, original future-target hashes, slice identities, counts, scoring invariants and acceptance remain exact; actual shares allow only summation roundoff. Strict loss failure remains recorded even if a different-fitted same-recipe portable build independently qualifies under the unchanged engineering gates. V5 labels are consumed.",
    }


def qualify_engineering_regression(
    continuity: dict, reproduced: dict, acceptance: dict, target_continuity: dict
) -> dict:
    """Distinguish exact local reproduction from a portable fitted variant."""
    exact_fit = (
        continuity["local_synthetic_fitted_fingerprint_exact_match"]
        and continuity["local_revenue_fitted_fingerprint_exact_match"]
    )
    mode = (
        "same_local_fitted_strict_metric_reproduction"
        if exact_fit
        else "same_recipe_portable_build_consumed_v5_regression"
    )
    passed = (
        continuity["source_and_policy_match"]
        and continuity["recipe_match"]
        and target_continuity["status"] == "pass"
        and reproduced["exact_invariant_status"] == "pass"
        and acceptance["status"] == "pass"
        and all(acceptance["checks"].values())
        and (not exact_fit or reproduced["status"] == "pass")
    )
    return {
        "mode": mode,
        "status": "pass" if passed else "fail",
        "strict_metric_reproduction_status": reproduced["status"],
        "is_exact_metric_reproduction": exact_fit and reproduced["status"] == "pass",
        "exact_identity_count_scoring_invariants": reproduced["exact_invariant_status"],
        "all_unchanged_five_engineering_gates": acceptance["status"],
        "pointwise_original_target_continuity": target_continuity["status"],
        "scope": "Same-local-fitted reruns must reproduce losses strictly. A differing-fitted portable build with exact source, policy, documents and recipes must independently pass every unchanged gate against pointwise-verified original stored targets, plus exact identities/counts/scoring invariants. Its actual losses and strict reproduction failures remain visible; it is neither a byte-identical predictor nor a new independent audit.",
    }


def evaluate(model_path: str | Path) -> dict:
    model = ForecastModel.load(model_path)
    baseline = synthetic_component_fingerprint(model)
    lineage = json.loads(
        Path(__file__)
        .parents[1]
        .joinpath("reports/external-audit-v2-lineage.json")
        .read_text()
    )
    original_baseline = lineage["synthetic_component_reference"]
    if baseline["recipe_sha256"] != original_baseline["recipe_sha256"]:
        raise ValueError("Synthetic comparator changed from the original audit recipe")
    identity = {
        "model_version": model.version,
        "audit_protocol_version": PROTOCOL_VERSION,
        "source_sha256": model.selection["source_sha256"],
        "frozen_protocol_document_sha256": hashlib.sha256(
            Path(__file__).parents[1].joinpath("data/audit-protocol-v5.md").read_bytes()
        ).hexdigest(),
        "candidate_addendum_document_sha256": hashlib.sha256(
            Path(__file__)
            .parents[1]
            .joinpath("data/audit-v5-candidate.md")
            .read_bytes()
        ).hexdigest(),
        "serving_policy": {
            "serving_mode": model.selection["serving_mode"],
            "expense_mode": model.expense_mode,
            "configured_real_weight": model.transfer_weight,
            "transfer_policy": model.transfer_policy,
            "expense_policy": model.expense_policy,
            "real_candidate": model.public_revenue_model.selected,
            "real_training_targets": model.public_revenue_model.metadata[
                "training_examples"
            ],
            "real_training_by_provider": model.public_revenue_model.metadata[
                "training_by_provider"
            ],
            "external_snapshot_sha256": model.public_revenue_model.metadata[
                "external_data_sha256"
            ],
        },
        "synthetic_comparator_fingerprint": baseline,
        "revenue_component_fingerprint": revenue_component_fingerprint(model),
    }
    archive = (
        Path(__file__).parents[1].joinpath("reports/engineering-audit-v5-frozen.json")
    )
    original, continuity, target_manifest, manifest_digest = None, None, None, None
    if archive.exists():
        archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if archive_digest != lineage["preserved_report_sha256"][archive.name]:
            raise ValueError("Preserved first V5 engineering report digest changed")
        original = json.loads(archive.read_text())
        original_identity = {
            **original,
            "revenue_component_fingerprint": lineage["revenue_component_fingerprint"],
        }
        continuity = validate_engineering_continuity(identity, original_identity)
        manifest_path = archive.with_name("engineering-audit-v5-targets.json")
        if not manifest_path.exists():
            raise ValueError("Frozen original V5 consumed-target manifest is missing")
        manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if manifest_digest != lineage["preserved_report_sha256"][manifest_path.name]:
            raise ValueError(
                "Frozen original V5 consumed-target manifest digest changed"
            )
        target_manifest = json.loads(manifest_path.read_text())
        validate_target_manifest(target_manifest, original, archive_digest)
    elif "engineering_v5_first_measurement" in lineage:
        raise ValueError("Preserved first V5 engineering report is missing")
    # All pipeline/recipe/policy/document checks above run before target creation.
    report = engineering_audit(model, target_manifest)
    reproduced = validate_reproduced_engineering(report, original) if original else None
    qualification = None
    if reproduced:
        qualification = qualify_engineering_regression(
            continuity,
            reproduced,
            report["predetermined_acceptance"],
            report["original_target_continuity"],
        )
        report["predetermined_acceptance"]["consumed_cohort_regression"] = (
            qualification["status"]
        )
        report["predetermined_acceptance"]["strict_metric_reproduction"] = reproduced[
            "status"
        ]
        if qualification["status"] != "pass":
            report["predetermined_acceptance"]["status"] = "fail"
    return {
        "measured_at_utc": datetime.now(UTC).isoformat(),
        **identity,
        "evaluation_status": (
            (
                "consumed_v5_same_recipe_portable_build_regression"
                if qualification["mode"]
                == "same_recipe_portable_build_consumed_v5_regression"
                else "consumed_v5_engineering_regression_reproduction_unchanged_pipeline"
            )
            if original
            else "reserved_new_synthetic_engineering_cohort_after_freeze"
        ),
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "formula_source_sha256": hashlib.sha256(
            Path(__file__).with_name("evaluate_fresh.py").read_bytes()
        ).hexdigest(),
        "synthetic_comparator_continuity": {
            "recipe_match": True,
            "local_fitted_fingerprint_exact_match": baseline["sha256"]
            == original_baseline["sha256"],
        },
        "engineering_continuity": continuity,
        "reproduced_engineering": reproduced,
        "engineering_regression_qualification": qualification,
        "original_target_manifest_sha256": manifest_digest,
        **report,
        "freshness_limit": (
            "The first Mac V5 result is preserved as engineering-audit-v5-frozen.json/.md. Original stored targets recover its raw ID/float64 hashes exactly; every native regenerated target is checked within 1e-9 absolute index precision before scoring, with native hash/deviation reported separately. Metrics use the stored original targets. Exact source, policies, protocol, candidate addendum and component recipes are required. Same-local-fitted reruns require strict loss reproduction. A differing-fitted portable same-recipe build instead must independently pass every unchanged engineering gate and exact identity/count/scoring invariants; its actual losses/deltas and any strict loss-reproduction FAIL remain visible. This is consumed-cohort regression, never new independent evidence or a byte-identical predictor. A revised serving pipeline requires new reserved targets and cannot retune on V5."
            if original
            else "These reserved seeds are not used in fitting, validation or tuning. Reruns reproduce the same frozen model; after inspecting results this cohort is consumed for subsequent model revisions. Do not retune on this audit."
        ),
        "truth_scope": "Every business, expense and future net-flow target in this report is synthetic. More real-trained forecast usage does not make expenses, capacity scores or repayment outcomes real-labeled. This is an engineering regression guard, not evidence of bank performance.",
        "audit_lineage": "Fourth exploratory sequential cycle: v2 rejected the 60%/25% policy because mean real weight 0.4969444444444444 missed the unchanged 0.50 gate; v3 and v4 both failed the unchanged 15% cohort-regression gate despite other aggregate/weight checks passing. Preserve all three outcomes as engineering-audit-v2-rejected.json/.md, engineering-audit-v3-rejected.json/.md and engineering-audit-v4-rejected.json/.md. History-only net reliability routers were explored exclusively on original training/development cases using already-observed historical 12-month target windows and finite margins 0/5/10/15; they were not selected for serving. The existing median_share12 observed-cost projection and guard65/25/25 policy are selected from the original finite grid with a tighter 10% development cohort buffer and accurately summed 55% development mean-share cushion. The independent audit remains 15% and mean50; reserved target labels supply no corrective coefficients. Real fitting recipe/candidate, generator, synthetic comparator recipe and audit thresholds remain frozen during policy reselection; portable fitted-byte differences are disclosed. V5 positions 4,000,000–4,000,899 were reserved before their target construction. Multiple failure-driven revisions make the development path exploratory; a later pass is not guaranteed superiority or an unconditional single-shot confidence claim.",
    }


def markdown(report: dict) -> str:
    selected, reference = report["selected"], report["fixed_synthetic_reference"]
    acceptance, improvement = report["predetermined_acceptance"], report["improvement"]
    improvement_value = improvement["macro_normalized_mae_improvement_pct"]
    improvement_text = (
        "undefined (zero baseline error)"
        if improvement_value is None
        else f"{improvement_value:.4f}%"
    )
    consumed = report.get("evaluation_status", "").startswith("consumed_v5_")
    portable = (
        report.get("evaluation_status")
        == "consumed_v5_same_recipe_portable_build_regression"
    )
    measurement_scope = (
        "This is a **same-recipe portable-build regression on consumed V5 targets**. Fitted estimators and actual losses may differ from the original Mac model; this build independently checks the unchanged engineering gates against the same stored targets. The first result remains in [the original V5 audit](engineering-audit-v5-frozen.json). This run adds no independent evidence and does not claim exact loss reproduction."
        if portable
        else (
            "This is a **consumed V5 regression reproduction** of the same synthetic cohort. The first result is preserved in [the original V5 audit](engineering-audit-v5-frozen.json); this run adds no independent evidence."
            if consumed
            else "This is a new **synthetic** cohort, not a real bank dataset."
        )
    )
    business_scope = (
        "originally unseen generated businesses"
        if consumed
        else "unseen generated businesses"
    )
    lines = [
        "# Portable-build consumed V5 engineering regression"
        if portable
        else (
            "# Consumed V5 engineering regression reproduction"
            if consumed
            else "# Reserved synthetic engineering audit"
        ),
        "",
        f"Measured {report['measured_at_utc']} with frozen model `{report['model_version']}`. {measurement_scope} Reproduce with `uv run python -m capacity_ml.evaluate_engineering`.",
        "",
        f"The unchanged generator uses reserved positions {report['protocol']['positions_inclusive'][0]:,}–{report['protocol']['positions_inclusive'][1]:,}, producing **{selected['businesses']} {business_scope} / {selected['observed_future_months']:,} future months**. Their latent cohorts/expense processes are not supplied to the forecast. Actual future net-flow SHA256: `{report['protocol']['future_net_sha256']}`.",
        "",
        "| Forecast | MAE (indices) | Macro history-normalized MAE | Absolute-net WAPE (%) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, values in (
        ("Frozen serving forecast", selected),
        ("Fixed synthetic reference", reference),
    ):
        wape = values["absolute_net_wape_pct"]
        lines.append(
            f"| {name} | {values['mae_index']:.4f} | {values['macro_business_normalized_mae']:.4f} | {'undefined' if wape is None else f'{wape:.4f}'} |"
        )
    lines.extend(
        [
            "",
            f"Macro normalized MAE improvement: **{improvement_text}**; whole-business bootstrap descriptive 95% interval `{improvement['business_bootstrap_95pct_interval']}` percentage points. The comparator is the unchanged selected synthetic HGB/net forecast on the same request, not a newly optimized baseline.",
            "",
            f"Actual real-trained component mean effective weight: **{100 * report['effective_real_weight']['mean']:.2f}%**, range {100 * report['effective_real_weight']['minimum']:.2f}–{100 * report['effective_real_weight']['maximum']:.2f}%. {report['effective_real_weight']['businesses_at_least_half']} businesses receive at least half real-trained contribution. Real candidate `{report['serving_policy']['real_candidate']}`; expense policy `{report['serving_policy']['expense_mode']}`.",
            "",
            f"Predetermined engineering acceptance: **{acceptance['status'].upper()}**. Macro normalized error may worsen no more than 2%, pooled indexed error no more than 5%, and each predeclared cohort error no more than 15%; mean effective real weight must reach 50% and the revenue candidate must use a real-trained estimator. These tolerances mean no material regression in a finite generated sample. They do not claim an accuracy gain when the measured difference is negative. Checks: `{acceptance['checks']}`.",
            "",
            "| Cohort | Businesses | Serving normalized MAE | Fixed synthetic normalized MAE |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for cohort, values in report["cohorts"].items():
        lines.append(
            f"| {cohort} | {values['selected']['businesses']} | {values['selected']['macro_business_normalized_mae']:.4f} | {values['fixed_synthetic_reference']['macro_business_normalized_mae']:.4f} |"
        )
    lines.extend(
        [
            "",
            f"The actual scoring path produced {report['scoring_flow']['valid_responses']} validated responses, {report['scoring_flow']['positive_principal_businesses']} positive indexed principal recommendations and {report['scoring_flow']['zero_principal_businesses']} zero-principal recommendations. Every adaptive schedule sums to its indexed principal. These checks do not establish realised affordability. Short-history slices and bootstrap details are in [the full JSON audit](engineering-metrics.json). WAPE retains zero and near-zero months and uses absolute actual net surplus in its denominator.",
            "",
            report["freshness_limit"],
            "",
            report["truth_scope"],
            "",
            report.get("audit_lineage", ""),
            "",
        ]
    )
    if consumed:
        reproduced = report["reproduced_engineering"]
        qualification = report.get("engineering_regression_qualification")
        qualification_text = (
            f"Consumed-cohort regression qualification: **{qualification['status'].upper()}**, mode `{qualification['mode']}`. "
            if qualification
            else ""
        )
        lines.extend(
            [
                f"{qualification_text}Strict metric reproduction against the first Mac result: **{reproduced['status'].upper()}**. Source, policy, recipes and protocol are checked before target reconstruction. Strict normalized MAE tolerance is `{reproduced['normalized_mae_absolute_tolerance']}`; indexed MAE tolerance `{reproduced['indexed_mae_absolute_tolerance']}`; percentages and descriptive interval bounds `{reproduced['percentage_and_interval_absolute_tolerance']}`. A same-local fitted model must meet these precisions. A differing-fitted portable build instead must independently pass all five unchanged gates, and retain any strict reproduction failure and every actual metric delta. IDs, original target hashes, slice identities, counts, actual shares and scoring invariants remain exact apart from declared summation roundoff. Continuity and measured deltas are in [the full JSON report](engineering-metrics.json).",
                "",
            ]
        )
        targets = report.get("original_target_continuity")
        if targets:
            lines.extend(
                [
                    f"Every one of **{targets['individual_targets_checked']:,} original target points** agrees with the native regenerated value within `{targets['absolute_target_tolerance']}` index units, with zero relative tolerance; maximum difference `{targets['maximum_absolute_native_target_difference']}`. Errors use the frozen original stored targets. Original raw float64 target SHA256 `{targets['original_future_net_sha256']}`; native regenerated SHA256 `{targets['native_regenerated_future_net_sha256']}`; exact raw-hash match `{targets['raw_float64_target_hash_exact_match']}`. The manifest recovers the first measurement's original ID/target hashes exactly; native platform differences are disclosed rather than silently dropped.",
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
    (destination / "engineering-metrics.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    (destination / "engineering-metrics.md").write_text(markdown(report))
    print(json.dumps(report["predetermined_acceptance"], indent=2, allow_nan=False))
    if report["predetermined_acceptance"]["status"] != "pass":
        raise SystemExit(
            "Frozen serving model failed reserved engineering audit; reports preserved"
        )


if __name__ == "__main__":
    main()
