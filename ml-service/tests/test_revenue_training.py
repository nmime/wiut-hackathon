import copy
import json

import numpy as np
import pytest

from capacity_ml.forecasting import TRANSFER_WEIGHTS, MonthlyHistory
from capacity_ml.public_revenue import (
    PublicCase,
    build_cases,
    fit_public_revenue_model,
    make_case,
    metrics,
)
from capacity_ml.revenue_data import REVENUE_PATH, load_revenue_series, parse_month
from scripts.import_revenue_data import SOURCES, build_source


def provider_payload(unit="in bln. Soums"):
    return json.dumps(
        [
            {
                "metadata": [
                    {"name_en": name, "value_en": value}
                    for name, value in {
                        "Unit of measurement": unit,
                        "Official statistics preparer": "National Statistics Committee",
                        "Indicator identification number (code)": "1.05.01.0120",
                        "Indicator name": "Monthly market services",
                        "Last modified date": "2026-09-24",
                        "Note": "Starting from September 2024, informal economy included.",
                    }.items()
                ],
                "data": [
                    {
                        "Code": "1703401",
                        "Klassifikator_en": "Synthetic parser fixture",
                        "2024-M01": 8,
                        "2024-M02": 7,
                        "2024-M03": 12,
                        "2025-M01": 2,
                        "2025-M02": 6,
                    }
                ],
            }
        ]
    ).encode()


def test_import_uses_declared_units_january_reset_and_preserves_revision():
    source = build_source(provider_payload(), SOURCES[1])
    assert source["source"]["published_to_million_uzs_multiplier"] == 1000
    assert source["source"]["license"] == "CC BY 4.0"
    assert source["series"][0]["monthly_million_uzs"] == [8000, -1000, 5000, 2000, 4000]
    assert source["quality_issues"][0]["reason"] == "negative_increment"
    with pytest.raises(ValueError, match="units changed"):
        build_source(provider_payload("unknown units"), SOURCES[1])
    malformed = json.loads(provider_payload())
    malformed[0]["data"][0]["2024-M01"] = True
    with pytest.raises(ValueError, match="Invalid provider YTD"):
        build_source(json.dumps(malformed).encode(), SOURCES[1])


def test_real_corpus_attribution_quality_and_regime_no_parent_duplicates():
    series, metadata = load_revenue_series()
    assert metadata["published_observations"] == 16544
    assert metadata["eligible_series"] == 440
    assert len({row.identity for row in series}) == len(series)
    assert {row.sector for row in series} == {
        "retail",
        "wholesale",
        "market_services",
        "accommodation_food",
    }
    for source in metadata["sources"]:
        assert source["license"] == "CC BY 4.0"
        assert source["landing_url"].startswith("https://siat.stat.uz/")
        assert len(source["raw_sha256"]) == 64
    for row in series:
        if row.sector in {"market_services", "accommodation_food"}:
            assert row.months[0] == parse_month("2024-10")
            assert len(row.identity.split(":")[1]) == 7
        else:
            assert len(row.identity.split(":")[1]) == 4
    additional = json.loads(REVENUE_PATH.read_text())
    assert all(data["quality_issues"] for data in additional["datasets"])
    assert any(np.any(row.values < 0) for row in series)


def test_real_splits_are_geographic_disjoint_and_future_targets_bounded():
    series, metadata = load_revenue_series()
    cases, excluded = build_cases(series, metadata)
    groups = {
        name: set(values) for name, values in metadata["geographic_groups"].items()
    }
    assert not groups["train"] & groups["validation"]
    assert not groups["train"] & groups["test"]
    assert not groups["validation"] & groups["test"]
    assert len(cases["train"]) == 740
    assert sum(len(case.actual) for case in cases["train"]) == 8880
    assert all(
        case.history.forecast_start + 11 <= parse_month("2025-12")
        for case in cases["train"]
    )
    assert all(len(case.actual) == 8 for case in cases["test_2026"])
    for split, rows in cases.items():
        membership = "test" if split.startswith("test") else split
        for case in rows:
            assert case.group in groups[membership]
            assert case.history.months[-1] < case.history.forecast_start
            assert np.all(np.isfinite(case.actual)) and np.all(case.actual >= 0)
    assert all(excluded.values())
    revised = next(
        row for row in series if row.sector == "wholesale" and np.any(row.values < 0)
    )
    negative = int(revised.months[np.flatnonzero(revised.values < 0)[0]])
    assert make_case(revised, negative, 12) is None


def test_test_revenue_changes_cannot_change_fit_or_validation_choice():
    series, metadata = load_revenue_series()
    before = fit_public_revenue_model((series, metadata))
    modified = copy.deepcopy(series)
    for row in modified:
        if row.group in metadata["geographic_groups"]["test"]:
            row.values[row.months >= parse_month("2025-01")] *= 9
    after = fit_public_revenue_model((modified, metadata))
    assert before.selected == after.selected
    assert before.metadata["validation"] == after.metadata["validation"]
    cases, _ = build_cases(series, metadata)
    changed, _ = build_cases(modified, metadata)
    np.testing.assert_array_equal(
        before.predict(cases["validation"][0].history),
        after.predict(cases["validation"][0].history),
    )
    assert not np.array_equal(
        cases["test_2025"][0].actual, changed["test_2025"][0].actual
    )


def test_real_artifact_and_transfer_choice_use_only_validation(model):
    public = model.public_revenue_model
    maes = public.metadata["validation"]
    qualified = public.metadata["candidate_qualification"]
    assert public.metadata["real_validation_best_candidate"] == min(
        (name for name in maes if qualified[name]),
        key=lambda name: maes[name]["normalized_mae"],
    )
    assert qualified[public.selected]
    assert public.metadata["uzbekistan_training_examples"] == 8880
    assert public.metadata["training_examples"] == sum(
        row["examples"] for row in public.metadata["training_by_provider"].values()
    )
    assert public.metadata["training_examples"] > 8880
    assert public.metadata["test_used_for_training_or_selection"] is False
    assert model.expense_estimator.n_features_in_ == model.estimator.n_features_in_
    transfer_mae = model.selection["transfer_validation_mae_index"]
    assert tuple(transfer_mae) == TRANSFER_WEIGHTS
    qualified_options = []
    for revenue_name, results in model.selection["joint_policy_validation"].items():
        for expense_mode, rows in results.items():
            baseline = rows["fixed_0"]["pooled_mae_index"]
            baseline_macro = rows["fixed_0"]["macro_normalized_mae"]
            for policy_name, row in rows.items():
                raw = row["pooled_mae_index"]
                macro = row["macro_normalized_mae"]
                cohort_gate = all(
                    value
                    <= rows["fixed_0"]["by_cohort_macro_normalized_mae"][cohort] * 1.15
                    for cohort, value in row["by_cohort_macro_normalized_mae"].items()
                )
                development_eligible = policy_name == "fixed_0" or (
                    revenue_name in model.selection["qualified_real_revenue_candidates"]
                    and raw < baseline
                    and macro <= baseline_macro * 1.02
                    and cohort_gate
                )
                from capacity_ml.train import FROZEN_REAL_REVENUE_CANDIDATE

                eligible = (
                    development_eligible
                    and revenue_name == FROZEN_REAL_REVENUE_CANDIDATE
                    and row["effective_real_weights"]["mean"] >= 0.55
                    and row["maximum_cohort_error_ratio_vs_synthetic"] <= 1.10
                )
                assert row["maximum_cohort_error_ratio_vs_synthetic"] == max(
                    value / rows["fixed_0"]["by_cohort_macro_normalized_mae"][cohort]
                    for cohort, value in row["by_cohort_macro_normalized_mae"].items()
                )
                assert row["development_robustness_eligible"] == (
                    row["maximum_cohort_error_ratio_vs_synthetic"] <= 1.10
                )
                assert row["development_eligible"] == development_eligible
                assert row["eligible"] == eligible
                if eligible:
                    qualified_options.append(
                        (raw, macro, revenue_name, expense_mode, policy_name)
                    )
    _, _, revenue_name, expense_mode, policy_name = min(qualified_options)
    assert model.selection["selected_transfer_policy"] == policy_name
    assert (
        model.transfer_policy
        == model.selection["selected_transfer_validation"]["policy"]
    )
    assert model.transfer_weight == model.transfer_policy["base_weight"]
    assert model.selection["selected_expense_policy"] == expense_mode
    assert (
        model.expense_policy == model.selection["expense_projection_grid"][expense_mode]
    )
    assert public.selected == revenue_name
    assert public.selected == FROZEN_REAL_REVENUE_CANDIDATE
    assert model.selection["minimum_development_mean_real_weight"] == 0.55
    assert model.selection["maximum_development_cohort_error_ratio"] == 1.10
    assert (
        model.selection["policy_reselection"][
            "final_audit_targets_used_for_reselection"
        ]
        is False
    )


def test_development_share_aggregation_preserves_exact_threshold_without_rounding():
    from capacity_ml.train import effective_weight_summary

    weights = [0.65] * 45 + [0.25] * 15
    summary = effective_weight_summary(weights)
    assert summary["mean"] == 0.55
    assert summary["by_weight"] == {"0.25": 15, "0.65": 45}
    assert summary["requests"] == 60
    below = weights.copy()
    below[0] -= 1e-9
    assert effective_weight_summary(below)["mean"] < 0.55


def test_real_revenue_predictions_scale_and_ignore_borrower_expense_series(model):
    series, metadata = load_revenue_series()
    cases, _ = build_cases(series, metadata)
    history = copy.deepcopy(cases["validation"][0].history)
    model_public = model.public_revenue_model
    original = model_public.predict(history)
    history.inflow *= 1e-6
    history.outflow[:] = 500  # Revenue-only model must not infer zero expenses as fact.
    np.testing.assert_allclose(
        model_public.predict(history), original * 1e-6, rtol=1e-8
    )


def test_zero_transfer_fast_path_avoids_unused_inference(
    model, score_request_input, monkeypatch
):
    from capacity_ml.forecasting import aggregate

    history = aggregate(score_request_input)
    synthetic = model.predict_synthetic(history)
    monkeypatch.setattr(model, "transfer_weight", 0)
    monkeypatch.setattr(model, "transfer_policy", None)

    def unused(*args):
        raise AssertionError("Rejected transfer component must not run during /score")

    monkeypatch.setattr(model.public_revenue_model, "predict", unused)
    monkeypatch.setattr(model.expense_estimator, "predict", unused)
    np.testing.assert_array_equal(model.predict(history), synthetic)


def test_zero_revenue_mape_and_wape_are_explicitly_undefined():
    case = PublicCase(
        "fixture",
        "retail",
        "fixture",
        MonthlyHistory(np.arange(3), np.ones(3), np.zeros(3), 3),
        np.zeros(12),
    )
    values = metrics([case], [np.ones(12)])
    assert values["mape_positive_actual_pct"] is None
    assert values["wape_pct"] is None
    assert values["mape_excluded_zero_months"] == 12


def test_revenue_feature_schema_baselines_and_observed_costs_are_scale_invariant():
    from capacity_ml.forecasting import observed_expense_forecast
    from capacity_ml.revenue_features import (
        REVENUE_FEATURE_NAMES,
        revenue_baselines,
        revenue_feature_matrix,
    )

    months = np.arange(2023 * 12, 2026 * 12)
    incoming = (
        100 * np.exp(np.arange(36) * 0.01) * (1 + 0.2 * np.sin(months * np.pi / 6))
    )
    history = MonthlyHistory(months, incoming, 0.65 * incoming + 8, 2026 * 12)
    future_revenue = np.linspace(150, 180, 12)
    original = revenue_feature_matrix(history)
    assert original.shape == (12, len(REVENUE_FEATURE_NAMES))
    assert np.all(np.isfinite(original))
    costs = observed_expense_forecast(history, future_revenue)
    np.testing.assert_allclose(costs, 0.65 * future_revenue + 8, rtol=1e-9)
    scaled = MonthlyHistory(
        months, history.inflow * 1e-7, history.outflow * 1e-7, history.forecast_start
    )
    np.testing.assert_allclose(
        revenue_feature_matrix(scaled), original, rtol=1e-8, atol=1e-10
    )
    for name, prediction in revenue_baselines(history).items():
        np.testing.assert_allclose(
            revenue_baselines(scaled)[name], prediction * 1e-7, rtol=1e-8
        )
    np.testing.assert_allclose(
        observed_expense_forecast(scaled, future_revenue * 1e-7),
        costs * 1e-7,
        rtol=1e-8,
    )


def test_transfer_regime_guard_uses_observed_history_and_is_scale_invariant():
    from capacity_ml.forecasting import transfer_policies, transfer_policy_weight

    policy = transfer_policies()["guard_0.6_0.25_0.25"]
    normal = MonthlyHistory(np.arange(24), np.full(24, 100.0), np.full(24, 70.0), 24)
    assert transfer_policy_weight(normal, policy) == 0.6
    short = MonthlyHistory(np.arange(3), np.full(3, 100.0), np.full(3, 70.0), 3)
    assert transfer_policy_weight(short, policy) == 0.25
    changed = copy.deepcopy(normal)
    changed.inflow[-3:] *= 2
    assert transfer_policy_weight(changed, policy) == 0.25
    changed.inflow *= 1e-8
    changed.outflow *= 1e-8
    changed.months += 5
    changed.forecast_start += 5
    assert transfer_policy_weight(changed, policy) == 0.25
    dormant = copy.deepcopy(normal)
    dormant.inflow[-12:] = 0
    dormant.outflow[-12:] = 0
    assert transfer_policy_weight(dormant, policy) == 0


def test_structural_active_share_floor_and_frozen_real_recipe():
    from capacity_ml.forecasting import (
        minimum_active_history_real_weight,
        transfer_policies,
    )
    from capacity_ml.train import (
        FROZEN_REAL_RECIPE_SHA256,
        real_component_recipe_digest,
    )

    policies = transfer_policies()
    assert minimum_active_history_real_weight(policies["fixed_0.5"]) == 0.5
    assert minimum_active_history_real_weight(policies["guard_0.6_0.25_0.25"]) == 0.25
    assert minimum_active_history_real_weight(policies["guard_0.6_0.5_0.5"]) == 0.5
    assert real_component_recipe_digest() == FROZEN_REAL_RECIPE_SHA256


def test_observed_expense_projection_grid_matches_selected_path_and_scale():
    from capacity_ml.forecasting import (
        expense_projection_policies,
        observed_expense_candidates,
        project_observed_expenses,
    )

    months = np.arange(36)
    incoming = 100 * (1 + 0.2 * np.sin(months * np.pi / 6))
    history = MonthlyHistory(months, incoming, incoming * 0.6 + 8, 36)
    revenues = np.linspace(90, 140, 12)
    candidates = observed_expense_candidates(history, revenues)
    assert len(candidates) == 24
    policies = expense_projection_policies()
    scaled = MonthlyHistory(months, history.inflow * 1e-8, history.outflow * 1e-8, 36)
    for name, prediction in candidates.items():
        assert np.all(np.isfinite(prediction)) and np.all(prediction >= 0)
        np.testing.assert_allclose(
            project_observed_expenses(history, revenues, policies[name]),
            prediction,
            rtol=1e-10,
        )
        np.testing.assert_allclose(
            project_observed_expenses(scaled, revenues * 1e-8, policies[name]),
            prediction * 1e-8,
            rtol=1e-8,
            atol=1e-14,
        )


def test_median_cost_share_uses_past_positive_inflow_and_zero_revenue_fallback():
    from capacity_ml.forecasting import project_observed_expenses

    months = np.arange(12)
    incoming = np.full(12, 100.0)
    outgoing = np.full(12, 60.0)
    outgoing[0] = 900  # A past outlier must not define the median projection.
    incoming[1] = 0
    history = MonthlyHistory(months, incoming, outgoing, 12)
    policy = {"kind": "observed_median_share", "history_months": 12}
    revenue = np.linspace(80, 120, 12)
    np.testing.assert_allclose(
        project_observed_expenses(history, revenue, policy), 0.6 * revenue
    )
    history.inflow[:] = 0
    np.testing.assert_allclose(
        project_observed_expenses(history, np.zeros(12), policy),
        np.full(12, np.mean(outgoing)),
    )


def test_serving_public_prediction_runs_only_selected_estimator(model, monkeypatch):
    from capacity_ml.forecasting import aggregate
    from capacity_ml.generator import generate_business

    public = copy.deepcopy(model.public_revenue_model)
    history = aggregate(generate_business("validation", 1).request())
    comparison = public.predict_candidates(history)[public.selected]

    def unused(*args, **kwargs):
        raise AssertionError("Unselected estimator must not run during serving")

    if public.selected == "gradient_boosting":
        monkeypatch.setattr(public.residual_estimator, "predict", unused)
    else:
        monkeypatch.setattr(public.estimator, "predict", unused)
        if public.selected in {
            "seasonal_naive",
            "damped_seasonal",
            "robust_harmonic",
            "trend_adjusted_seasonal",
        }:
            monkeypatch.setattr(public.residual_estimator, "predict", unused)
    np.testing.assert_allclose(public.predict(history), comparison, rtol=1e-10)


def test_zero_revenue_returns_zero_without_trained_inference(model, monkeypatch):
    public = copy.deepcopy(model.public_revenue_model)
    history = MonthlyHistory(np.arange(24), np.zeros(24), np.ones(24), 24)

    def unused(*args, **kwargs):
        raise AssertionError("No observed revenue must not invent model revenue")

    monkeypatch.setattr(public.estimator, "predict", unused)
    monkeypatch.setattr(public.residual_estimator, "predict", unused)
    np.testing.assert_array_equal(public.predict(history), np.zeros(12))


def test_dormant_history_does_not_invent_scale_dependent_forecast(model, monkeypatch):
    dormant = MonthlyHistory(
        np.arange(36),
        np.r_[np.full(24, 100.0), np.zeros(12)],
        np.r_[np.full(24, 60.0), np.zeros(12)],
        36,
    )

    def unused(*args, **kwargs):
        raise AssertionError(
            "A year with no observed activity has no forecastable recent scale"
        )

    monkeypatch.setattr(model.estimator, "predict", unused)
    np.testing.assert_array_equal(model.predict(dormant), np.zeros(12))
    np.testing.assert_array_equal(
        model.public_revenue_model.predict(dormant), np.zeros(12)
    )


def test_real_features_preserve_observed_seasonal_phase_under_calendar_shift():
    from capacity_ml.revenue_features import revenue_baselines, revenue_feature_matrix

    months = np.arange(2020 * 12, 2023 * 12)
    incoming = (
        100 * np.exp(np.arange(36) * 0.006) * (1 + 0.3 * np.sin(months * np.pi / 6))
    )
    original = MonthlyHistory(months, incoming, 0.65 * incoming, int(months[-1]) + 1)
    shifted = MonthlyHistory(
        months + 5, incoming, 0.65 * incoming, original.forecast_start + 5
    )
    np.testing.assert_allclose(
        revenue_feature_matrix(original),
        revenue_feature_matrix(shifted),
        rtol=1e-9,
        atol=1e-10,
    )
    for name, predicted in revenue_baselines(original).items():
        np.testing.assert_allclose(
            revenue_baselines(shifted)[name], predicted, rtol=1e-9, atol=1e-10
        )


def test_real_expert_selection_uses_only_known_historical_targets(model, monkeypatch):
    from capacity_ml.public_revenue import EXPERT_CANDIDATES

    public = copy.deepcopy(model.public_revenue_model)
    months = np.arange(2020 * 12, 2024 * 12)
    observed = np.linspace(100, 180, 48)
    history = MonthlyHistory(months, observed, np.zeros(48), int(months[-1]) + 1)
    cutoffs = []

    def inspect(earlier):
        cutoffs.append(len(earlier.months))
        assert len(earlier.months) >= 12
        assert len(earlier.months) + 12 <= len(history.months)
        assert earlier.forecast_start == earlier.months[-1] + 1
        assert earlier.months[-1] < history.forecast_start
        np.testing.assert_array_equal(earlier.inflow, observed[: len(earlier.months)])
        return {
            name: np.full(12, np.mean(earlier.inflow)) for name in EXPERT_CANDIDATES
        }

    monkeypatch.setattr(public, "_trained_forecasts", inspect)
    errors = public._past_expert_errors(history)
    assert cutoffs == [24, 30, 36]
    assert set(errors) == set(EXPERT_CANDIDATES)


def test_forecast_provenance_matches_prediction_and_dormant_zero(model):
    from capacity_ml.forecasting import aggregate
    from capacity_ml.generator import generate_business

    history = aggregate(generate_business("validation", 1).request())
    predicted, weight = model.predict_with_provenance(history)
    assert weight == model.effective_real_weight(history)
    assert weight == model.effective_transfer_weight(history)
    np.testing.assert_array_equal(predicted, model.predict(history))
    dormant = MonthlyHistory(np.arange(24), np.zeros(24), np.zeros(24), 24)
    predicted, weight = model.predict_with_provenance(dormant)
    assert weight == 0
    np.testing.assert_array_equal(predicted, np.zeros(12))
