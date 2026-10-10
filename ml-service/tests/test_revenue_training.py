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
    assert public.selected == min(
        (name for name in maes if qualified[name]),
        key=lambda name: maes[name]["normalized_mae"],
    )
    assert public.metadata["uzbekistan_training_examples"] == 8880
    assert public.metadata["training_examples"] == sum(
        row["examples"] for row in public.metadata["training_by_provider"].values()
    )
    assert public.metadata["training_examples"] > 8880
    assert public.metadata["test_used_for_training_or_selection"] is False
    assert model.expense_estimator.n_features_in_ == model.estimator.n_features_in_
    transfer_mae = model.selection["transfer_validation_mae_index"]
    assert tuple(transfer_mae) == TRANSFER_WEIGHTS
    results = model.selection["transfer_validation"]
    qualified = []
    for expense_mode, row in results.items():
        baseline = row["pooled_mae_index"][0]
        baseline_macro = row["macro_normalized_mae"][0]
        for weight in TRANSFER_WEIGHTS:
            raw = row["pooled_mae_index"][weight]
            macro = row["macro_normalized_mae"][weight]
            if weight == 0 or (
                public.metadata["selected_uses_trained_estimator"]
                and model.selection["real_validation_skill_vs_seasonal"] >= 0.05
                and raw < baseline
                and macro <= baseline_macro * 1.02
            ):
                qualified.append((raw, macro, expense_mode, weight))
    _, _, expense_mode, weight = min(qualified)
    assert model.transfer_weight == weight
    assert model.expense_mode == expense_mode


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
