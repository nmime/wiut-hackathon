import copy
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from capacity_ml.evaluate_engineering import (
    markdown as engineering_markdown,
)
from capacity_ml.evaluate_engineering import (
    qualify_engineering_regression,
    validate_engineering_continuity,
    validate_reproduced_engineering,
    validate_target_manifest,
)
from capacity_ml.evaluate_external import (
    validate_external_isolation,
    validate_reproduced_losses,
    validate_revenue_continuity,
)
from capacity_ml.evaluate_fresh import (
    ENGINEERING_POSITIONS,
    PROTOCOL_VERSION,
    business_improvement_interval,
    engineering_acceptance,
    external_acceptance,
    net_metrics,
    validate_original_target_pointwise,
)


def toy_engineering_report():
    actual = [np.ones(12), np.ones(12)]
    predicted = [np.full(12, 0.9), np.full(12, 0.9)]
    baseline = [np.full(12, 0.8), np.full(12, 0.8)]
    comparison = {
        "selected": net_metrics(actual, predicted, [1, 1]),
        "fixed_synthetic_reference": net_metrics(actual, baseline, [1, 1]),
        "improvement": business_improvement_interval(
            actual, predicted, baseline, [1, 1]
        ),
    }
    report = {
        **comparison,
        "model_version": "test-only-frozen-version",
        "source_sha256": "test-only-frozen-source",
        "audit_protocol_version": PROTOCOL_VERSION,
        "frozen_protocol_document_sha256": "test-only-protocol",
        "candidate_addendum_document_sha256": "test-only-addendum",
        "measured_at_utc": "2026-10-11T00:00:00Z",
        "serving_policy": {
            "serving_mode": "test_only",
            "expense_mode": "observed_cost_projection",
            "configured_real_weight": 0.65,
            "transfer_policy": {"kind": "fixed", "base_weight": 0.65},
            "expense_policy": {"kind": "observed_median_share", "history_months": 12},
            "real_candidate": "test-only-trained-candidate",
            "real_training_targets": 2,
            "real_training_by_provider": {"test_only": {"examples": 2}},
            "external_snapshot_sha256": "test-only-snapshot",
        },
        "synthetic_comparator_fingerprint": {
            "recipe_sha256": "test-only-synthetic-recipe",
            "sha256": "test-only-synthetic-fitted",
        },
        "revenue_component_fingerprint": {
            "recipe_sha256": "test-only-revenue-recipe",
            "sha256": "test-only-revenue-fitted",
        },
        "protocol": {
            "positions_inclusive": [4_000_000, 4_000_899],
            "businesses": 2,
            "generator_unchanged": True,
            "ids_sha256": "test-only-ids",
            "future_net_sha256": "test-only-targets",
        },
        "cohorts": {"test_only": copy.deepcopy(comparison)},
        "history_length": {"test_only": copy.deepcopy(comparison)},
        "effective_real_weight": {
            "mean": 0.65,
            "minimum": 0.65,
            "maximum": 0.65,
            "businesses_at_least_half": 2,
        },
        "selected_uses_real_trained_estimator": True,
        "scoring_flow": {
            "valid_responses": 2,
            "positive_principal_businesses": 1,
            "zero_principal_businesses": 1,
            "schedule_principal_sums_checked": True,
            "real_bank_capacity_validated": False,
        },
        "freshness_limit": "Test-only consumed cohort",
        "truth_scope": "Test-only synthetic targets",
    }
    report["predetermined_acceptance"] = engineering_acceptance(report)
    return report


def toy_target_manifest():
    original = toy_engineering_report()
    start = original["protocol"]["positions_inclusive"][0]
    original["protocol"]["positions_inclusive"][1] = start + 1
    cases, ids, target_hash = [], [], hashlib.sha256()
    for index in range(2):
        business_id = f"test-only-{index}"
        values = np.asarray([0, 1e-10, -2, 3] * 3, dtype=np.float64)
        ids.append(business_id)
        target_hash.update(business_id.encode())
        target_hash.update(values.astype("<f8").tobytes())
        cases.append(
            {
                "business_id": business_id,
                "position": start + index,
                "cohort": "test_only",
                "forecast_month_ids": list(range(100, 112)),
                "future_net": values.tolist(),
            }
        )
    original["protocol"]["ids_sha256"] = hashlib.sha256(
        "\n".join(ids).encode()
    ).hexdigest()
    original["protocol"]["future_net_sha256"] = target_hash.hexdigest()
    manifest = {
        "source_sha256": original["source_sha256"],
        "protocol_version": original["audit_protocol_version"],
        "original_report_sha256": "test-only-archive-hash",
        "pointwise_absolute_target_tolerance": 1e-9,
        "pointwise_relative_target_tolerance": 0,
        "original_ids_sha256": original["protocol"]["ids_sha256"],
        "original_future_net_sha256": target_hash.hexdigest(),
        "cases": cases,
    }
    return manifest, original


def test_net_metrics_preserve_negative_and_nearzero_actuals():
    actual = [np.asarray([0, 1e-10, -2, 2] * 3)]
    predicted = [np.zeros(12)]
    values = net_metrics(actual, predicted, [2])
    assert values["mae_index"] == pytest.approx(1)
    assert values["macro_business_normalized_mae"] == pytest.approx(0.5)
    assert values["absolute_net_wape_pct"] == 100
    assert values["wape_excluded_zero_or_nearzero_months"] == 0
    zero = net_metrics([np.zeros(12)], [np.zeros(12)], [1])
    assert zero["absolute_net_wape_pct"] is None


def test_whole_business_bootstrap_deterministic_and_scales_normalized_errors():
    actual = [np.ones(12), np.ones(12) * 10]
    forecast = [np.ones(12) * 0.9, np.ones(12) * 9]
    baseline = [np.ones(12) * 0.8, np.ones(12) * 8]
    interval = business_improvement_interval(actual, forecast, baseline, [1, 10])
    assert interval == business_improvement_interval(
        actual, forecast, baseline, [1, 10]
    )
    assert interval["macro_normalized_mae_improvement_pct"] == pytest.approx(50)
    np.testing.assert_allclose(interval["business_bootstrap_95pct_interval"], [50, 50])
    assert interval["independent_generated_business_seeds"] == 2


def test_frozen_engineering_positions_are_separate_without_generating_targets():
    assert ENGINEERING_POSITIONS.start == 4_000_000
    assert ENGINEERING_POSITIONS.stop == 4_000_900
    assert len(ENGINEERING_POSITIONS) == 900
    assert not set(ENGINEERING_POSITIONS) & set(range(120))
    assert not set(ENGINEERING_POSITIONS) & set(range(1_000_000, 1_000_180))
    assert not set(ENGINEERING_POSITIONS) & set(range(2_000_000, 2_000_900))
    assert not set(ENGINEERING_POSITIONS) & set(range(3_000_000, 3_000_900))


def passing_engineering_report():
    return {
        "selected": {"macro_business_normalized_mae": 1.02, "mae_index": 105},
        "fixed_synthetic_reference": {
            "macro_business_normalized_mae": 1,
            "mae_index": 100,
        },
        "cohorts": {
            "test_only": {
                "selected": {"macro_business_normalized_mae": 1.15},
                "fixed_synthetic_reference": {"macro_business_normalized_mae": 1},
            }
        },
        "effective_real_weight": {"mean": 0.5},
        "selected_uses_real_trained_estimator": True,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("macro", 1.02001),
        ("raw", 105.01),
        ("cohort", 1.15001),
        ("weight", 0.49999),
        ("trained", False),
    ],
)
def test_every_engineering_guard_rejects_violations(field, value):
    report = passing_engineering_report()
    assert engineering_acceptance(report)["status"] == "pass"
    changed = copy.deepcopy(report)
    if field == "macro":
        changed["selected"]["macro_business_normalized_mae"] = value
    elif field == "raw":
        changed["selected"]["mae_index"] = value
    elif field == "cohort":
        changed["cohorts"]["test_only"]["selected"]["macro_business_normalized_mae"] = (
            value
        )
    elif field == "weight":
        changed["effective_real_weight"]["mean"] = value
    else:
        changed["selected_uses_real_trained_estimator"] = value
    assert engineering_acceptance(changed)["status"] == "fail"


def test_external_acceptance_uses_only_predeclared_positive_skill_provider_limits():
    audit = {
        "overall": {"improvement": {"macro_case_normalized_mae_improvement_pct": 0.01}},
        "providers": {
            "test_only": {
                "improvement": {"macro_case_normalized_mae_improvement_pct": -10}
            }
        },
    }
    assert external_acceptance(audit)["status"] == "pass"
    missing = external_acceptance(audit, {"test_only", "unavailable_provider"})
    assert missing["status"] == "fail"
    assert missing["missing_expected_providers"] == ["unavailable_provider"]
    audit["providers"]["test_only"]["improvement"][
        "macro_case_normalized_mae_improvement_pct"
    ] = -10.001
    assert external_acceptance(audit)["status"] == "fail"
    audit["providers"]["test_only"]["improvement"][
        "macro_case_normalized_mae_improvement_pct"
    ] = 10
    audit["overall"]["improvement"]["macro_case_normalized_mae_improvement_pct"] = 0
    assert external_acceptance(audit)["status"] == "fail"


def test_invalid_shapes_nonfinite_values_and_scales_fail():
    for target, prediction, scale in (
        (np.ones(3), np.ones(12), 1),
        (np.ones(12), np.full(12, np.nan), 1),
        (np.ones(12), np.ones(12), 0),
    ):
        with pytest.raises(ValueError):
            net_metrics([target], [prediction], [scale])
    with pytest.raises(ValueError, match="nonempty"):
        net_metrics([], [], [])


def test_external_snapshot_and_whole_provider_isolation_are_enforced():
    metadata = {"data_sha256": "test-only-digest"}
    fit = {
        "external_data_sha256": "test-only-digest",
        "training_by_provider": {"eurostat": {"examples": 10}},
        "combined_validation": {"test_only": {"by_provider": {"eurostat": {}}}},
    }
    validate_external_isolation(fit, metadata)
    wrong = copy.deepcopy(fit)
    wrong["external_data_sha256"] = "mismatch"
    with pytest.raises(ValueError, match="snapshot differs"):
        validate_external_isolation(wrong, metadata)
    wrong = copy.deepcopy(fit)
    wrong["training_by_provider"]["ons"] = {"examples": 1}
    with pytest.raises(ValueError, match="entered training"):
        validate_external_isolation(wrong, metadata)
    wrong = copy.deepcopy(fit)
    wrong["combined_validation"]["test_only"]["by_provider"]["ons"] = {}
    with pytest.raises(ValueError, match="entered selection"):
        validate_external_isolation(wrong, metadata)


def test_external_continuity_requires_frozen_recipe_and_selected_candidate():
    original = {
        "sha256": "test-only-fitted-hash",
        "recipe_sha256": "test-only-recipe",
        "selected_candidate": "test-only-candidate",
    }
    lineage = {"revenue_component_fingerprint": original}
    assert validate_revenue_continuity(original, lineage)[
        "fitted_fingerprint_exact_match"
    ]
    portable = {**original, "sha256": "different-platform-fitted-hash"}
    assert not validate_revenue_continuity(portable, lineage)[
        "fitted_fingerprint_exact_match"
    ]
    for field in ("recipe_sha256", "selected_candidate"):
        with pytest.raises(ValueError, match="recipe differs"):
            validate_revenue_continuity({**original, field: "changed"}, lineage)


def test_external_reproduction_checks_losses_counts_and_undefined_status():
    metrics = {
        "macro_case_normalized_mae": 0.1,
        "normalized_mae": 0.1,
        "smape_pct": 5,
        "normalized_wape_pct": 6,
        "mae_provider_units": None,
        "wape_pct": None,
        "series": 2,
        "months": 24,
        "unique_target_observations": 24,
        "entity_groups": 2,
    }
    original = {
        "overall": {"selected": metrics},
        "providers": {"test-only-provider": {"selected": metrics}},
    }
    reproduced = copy.deepcopy(original)
    reproduced["overall"]["selected"]["normalized_mae"] += 5e-10
    assert validate_reproduced_losses(reproduced, original)["status"] == "pass"
    for field, value in (
        ("normalized_mae", 0.100000002),
        ("months", 23),
        ("wape_pct", 0),
    ):
        reproduced = copy.deepcopy(original)
        reproduced["overall"]["selected"][field] = value
        assert validate_reproduced_losses(reproduced, original)["status"] == "fail"


@pytest.mark.parametrize(
    "field",
    [
        "model_version",
        "source_sha256",
        "audit_protocol_version",
        "frozen_protocol_document_sha256",
        "candidate_addendum_document_sha256",
        "serving_policy",
        "synthetic_comparator_fingerprint",
        "revenue_component_fingerprint",
    ],
)
def test_engineering_consumed_cohort_rejects_changed_pipeline_identity(field):
    original = toy_engineering_report()
    assert validate_engineering_continuity(original, original)["recipe_match"]
    changed = copy.deepcopy(original)
    if field == "serving_policy":
        changed[field]["expense_policy"]["history_months"] = 6
    elif "fingerprint" in field:
        changed[field]["recipe_sha256"] = "changed-test-only-recipe"
    else:
        changed[field] = "changed-test-only-identity"
    with pytest.raises(ValueError, match="continuity changed"):
        validate_engineering_continuity(changed, original)


def test_engineering_portable_fitted_difference_requires_loss_reproduction():
    original = toy_engineering_report()
    current = copy.deepcopy(original)
    for field in ("synthetic_comparator_fingerprint", "revenue_component_fingerprint"):
        current[field]["sha256"] = "different-platform-learned-bytes"
    continuity = validate_engineering_continuity(current, original)
    assert continuity["recipe_match"]
    assert not continuity["local_synthetic_fitted_fingerprint_exact_match"]
    assert not continuity["local_revenue_fitted_fingerprint_exact_match"]
    current["selected"]["macro_business_normalized_mae"] += 5e-10
    current["selected"]["mae_index"] += 5e-7
    assert validate_reproduced_engineering(current, original)["status"] == "pass"
    current["cohorts"]["test_only"]["selected"]["macro_business_normalized_mae"] += 2e-9
    assert validate_reproduced_engineering(current, original)["status"] == "fail"


@pytest.mark.parametrize(
    "field",
    [
        "ids",
        "targets",
        "count",
        "cohort",
        "history",
        "weight",
        "interval",
        "acceptance",
        "undefined",
    ],
)
def test_engineering_reproduction_rejects_cohort_hash_count_and_metric_changes(field):
    original = toy_engineering_report()
    current = copy.deepcopy(original)
    if field == "ids":
        current["protocol"]["ids_sha256"] = "changed"
    elif field == "targets":
        current["protocol"]["future_net_sha256"] = "changed"
    elif field == "count":
        current["selected"]["observed_future_months"] -= 1
    elif field == "cohort":
        current["cohorts"]["renamed"] = current["cohorts"].pop("test_only")
    elif field == "history":
        current["history_length"]["test_only"]["selected"]["mae_index"] += 2e-6
    elif field == "weight":
        current["effective_real_weight"]["mean"] += 2e-12
    elif field == "interval":
        current["improvement"]["business_bootstrap_95pct_interval"][0] += 2e-6
    elif field == "acceptance":
        current["predetermined_acceptance"]["status"] = "fail"
    else:
        current["selected"]["absolute_net_wape_pct"] = None
    assert validate_reproduced_engineering(current, original)["status"] == "fail"


def test_engineering_markdown_labels_consumed_reproduction_without_new_evidence():
    original = toy_engineering_report()
    original["evaluation_status"] = (
        "reserved_new_synthetic_engineering_cohort_after_freeze"
    )
    assert "This is a new **synthetic** cohort" in engineering_markdown(original)
    current = copy.deepcopy(original)
    current["evaluation_status"] = (
        "consumed_v5_engineering_regression_reproduction_unchanged_pipeline"
    )
    current["reproduced_engineering"] = validate_reproduced_engineering(
        current, original
    )
    text = engineering_markdown(current)
    assert "consumed V5 regression reproduction" in text
    assert "originally unseen generated businesses" in text
    assert "This is a new **synthetic** cohort" not in text
    assert "adds no independent evidence" in text


def test_engineering_source_guard_runs_before_any_target_construction(
    tmp_path, monkeypatch
):
    from capacity_ml import evaluate_engineering

    original = toy_engineering_report()
    package = tmp_path / "capacity_ml"
    package.mkdir()
    monkeypatch.setattr(
        evaluate_engineering, "__file__", str(package / "evaluate_engineering.py")
    )
    reports, data = tmp_path / "reports", tmp_path / "data"
    reports.mkdir()
    data.mkdir()
    for name, field in (
        ("audit-protocol-v5.md", "frozen_protocol_document_sha256"),
        ("audit-v5-candidate.md", "candidate_addendum_document_sha256"),
    ):
        path = data / name
        path.write_text("test-only immutable document")
        original[field] = hashlib.sha256(path.read_bytes()).hexdigest()
    archive = reports / "engineering-audit-v5-frozen.json"
    archive.write_text(json.dumps(original))
    lineage = {
        "synthetic_component_reference": original["synthetic_comparator_fingerprint"],
        "revenue_component_fingerprint": original["revenue_component_fingerprint"],
        "preserved_report_sha256": {
            archive.name: hashlib.sha256(archive.read_bytes()).hexdigest()
        },
    }
    (reports / "external-audit-v2-lineage.json").write_text(json.dumps(lineage))
    policy = original["serving_policy"]
    fake_model = SimpleNamespace(
        version=original["model_version"],
        selection={
            "source_sha256": "changed-source",
            "serving_mode": policy["serving_mode"],
        },
        expense_mode=policy["expense_mode"],
        transfer_weight=policy["configured_real_weight"],
        transfer_policy=policy["transfer_policy"],
        expense_policy=policy["expense_policy"],
        public_revenue_model=SimpleNamespace(
            selected=policy["real_candidate"],
            metadata={
                "training_examples": policy["real_training_targets"],
                "training_by_provider": policy["real_training_by_provider"],
                "external_data_sha256": policy["external_snapshot_sha256"],
            },
        ),
    )
    monkeypatch.setattr(
        evaluate_engineering.ForecastModel, "load", lambda _: fake_model
    )
    monkeypatch.setattr(
        evaluate_engineering,
        "synthetic_component_fingerprint",
        lambda _: original["synthetic_comparator_fingerprint"],
    )
    monkeypatch.setattr(
        evaluate_engineering,
        "revenue_component_fingerprint",
        lambda _: original["revenue_component_fingerprint"],
    )

    def forbidden_construction(_):
        raise AssertionError("Consumed targets must not be built for changed source")

    monkeypatch.setattr(
        evaluate_engineering, "engineering_audit", forbidden_construction
    )
    with pytest.raises(ValueError, match="source_sha256"):
        evaluate_engineering.evaluate("test-only-ignored-path")


def test_original_target_manifest_recovers_raw_hashes_and_rejects_changed_values():
    manifest, original = toy_target_manifest()
    validate_target_manifest(manifest, original, "test-only-archive-hash")
    # Even a tiny stored-reference edit is forbidden: only regenerated values
    # may have platform roundoff within the separate pointwise tolerance.
    changed = copy.deepcopy(manifest)
    changed["cases"][0]["future_net"][0] += 1e-10
    with pytest.raises(ValueError, match="hashes/counts"):
        validate_target_manifest(changed, original, "test-only-archive-hash")
    changed = copy.deepcopy(manifest)
    changed["cases"][0]["forecast_month_ids"][0] += 1
    with pytest.raises(ValueError, match="point/month schema"):
        validate_target_manifest(changed, original, "test-only-archive-hash")
    changed = copy.deepcopy(manifest)
    changed["pointwise_absolute_target_tolerance"] = 1e-6
    with pytest.raises(ValueError, match="provenance"):
        validate_target_manifest(changed, original, "test-only-archive-hash")


def test_every_native_target_is_checked_then_original_targets_are_used():
    manifest, _ = toy_target_manifest()
    case = manifest["cases"][0]
    native = np.asarray(case["future_net"]) + 5e-10
    checked, maximum = validate_original_target_pointwise(
        case["business_id"],
        case["position"],
        case["cohort"],
        np.asarray(case["forecast_month_ids"]),
        native,
        case,
    )
    np.testing.assert_array_equal(checked, case["future_net"])
    assert maximum == pytest.approx(5e-10)
    native[11] += 2e-9
    with pytest.raises(ValueError, match="beyond"):
        validate_original_target_pointwise(
            case["business_id"],
            case["position"],
            case["cohort"],
            np.asarray(case["forecast_month_ids"]),
            native,
            case,
        )
    with pytest.raises(ValueError, match="identity/month"):
        validate_original_target_pointwise(
            "wrong-case",
            case["position"],
            case["cohort"],
            np.asarray(case["forecast_month_ids"]),
            native,
            case,
        )


def test_same_local_fitted_rerun_stays_strict_but_portable_gates_are_independent():
    original = toy_engineering_report()
    current = copy.deepcopy(original)
    current["selected"]["mae_index"] += 0.01
    reproduced = validate_reproduced_engineering(current, original)
    assert reproduced["status"] == "fail"
    assert reproduced["exact_invariant_status"] == "pass"
    assert reproduced["measured_metric_deltas_from_first_mac_result"][
        "overall.selected.mae_index"
    ] == pytest.approx(0.01)
    continuity = {
        "source_and_policy_match": True,
        "recipe_match": True,
        "local_synthetic_fitted_fingerprint_exact_match": True,
        "local_revenue_fitted_fingerprint_exact_match": True,
    }
    targets = {"status": "pass"}
    acceptance = engineering_acceptance(current)
    assert acceptance["status"] == "pass"
    strict = qualify_engineering_regression(continuity, reproduced, acceptance, targets)
    assert strict["status"] == "fail"
    continuity["local_synthetic_fitted_fingerprint_exact_match"] = False
    portable = qualify_engineering_regression(
        continuity, reproduced, acceptance, targets
    )
    assert portable["mode"] == "same_recipe_portable_build_consumed_v5_regression"
    assert portable["status"] == "pass"
    assert portable["strict_metric_reproduction_status"] == "fail"
    assert not portable["is_exact_metric_reproduction"]
    current["cohorts"]["test_only"]["selected"]["macro_business_normalized_mae"] = 1
    assert (
        qualify_engineering_regression(
            continuity, reproduced, engineering_acceptance(current), targets
        )["status"]
        == "fail"
    )
    targets["status"] = "fail"
    assert (
        qualify_engineering_regression(continuity, reproduced, acceptance, targets)[
            "status"
        ]
        == "fail"
    )
    targets["status"] = "pass"
    current["protocol"]["future_net_sha256"] = "changed"
    invariant_failure = validate_reproduced_engineering(current, original)
    assert (
        qualify_engineering_regression(
            continuity, invariant_failure, acceptance, targets
        )["status"]
        == "fail"
    )


def test_portable_markdown_retains_strict_failure_without_exact_reproduction_claim():
    original = toy_engineering_report()
    current = copy.deepcopy(original)
    current["selected"]["mae_index"] += 0.01
    current["evaluation_status"] = "consumed_v5_same_recipe_portable_build_regression"
    current["reproduced_engineering"] = validate_reproduced_engineering(
        current, original
    )
    current["engineering_regression_qualification"] = {
        "mode": "same_recipe_portable_build_consumed_v5_regression",
        "status": "pass",
    }
    text = engineering_markdown(current)
    assert "same-recipe portable-build regression on consumed V5 targets" in text
    assert "Strict metric reproduction against the first Mac result: **FAIL**" in text
    assert "does not claim exact loss reproduction" in text
    assert "adds no independent evidence" in text
