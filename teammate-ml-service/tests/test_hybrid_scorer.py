"""All borrower observations/forecasts here are disclosed synthetic test fixtures."""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from hybrid.backtest import compare_actual_surplus
from hybrid.scorer import (
    LEVELS,
    MIN_OFFER_SHARE_OF_BUDGET,
    HybridEngine,
    HybridInputError,
    assess_request,
    persistent_decline,
)
from teammate_bridge.schemas import ScoreRequest, ScoreResponse

PATTERN = np.asarray(
    [
        150000,
        150000,
        250000,
        400000,
        550000,
        550000,
        450000,
        300000,
        200000,
        150000,
        150000,
        150000,
    ],
    dtype=float,
)


def fixture(history=None, median=None, spread=10000.0, requested=None):
    history = (
        np.tile(PATTERN, 2) if history is None else np.asarray(history, dtype=float)
    )
    median = PATTERN.copy() if median is None else np.asarray(median, dtype=float)
    final = 2024 * 12 + 11
    months = list(range(final - len(history) + 1, final + 1))
    labels = [f"{month // 12:04d}-{month % 12 + 1:02d}" for month in months]
    transactions = []
    for label, incoming in zip(labels, history, strict=True):
        if incoming > 0:
            transactions.append(
                {
                    "ts": label + "-05T12:00:00+05:00",
                    "direction": "in",
                    "channel": "card",
                    "amount_index": float(incoming),
                }
            )
        transactions.append(
            {
                "ts": label + "-06T12:00:00+05:00",
                "direction": "out",
                "channel": "transfer",
                "amount_index": 50000.0,
            }
        )
    payload = ScoreRequest.model_validate(
        {
            "business_id": "test-only-hybrid-borrower",
            "as_of_date": "2024-12-31",
            "currency": "UZS",
            "requested_amount": requested,
            "transactions": transactions,
        }
    )
    forecast = {
        "months": [f"2025-{month:02d}" for month in range(1, 13)],
        "median": median.tolist(),
        "revenue_grid": np.maximum(
            median[:, None] + (LEVELS[None, :] - 0.5) * spread, 0
        ).tolist(),
        "quantile_levels": LEVELS.tolist(),
        "observed_outflow_projection": [50000.0] * 12,
        "history_months": labels,
        "history_inflow": history.tolist(),
        "history_outflow": [50000.0] * len(history),
        "expense_policy": "observed_cost_projection",
        "provenance": {
            "revenue_model_version": "test-only-revenue-model",
            "real_training_targets": 0,
            "model_artifact_sha256": "1" * 64,
            "calibration_sha256": "2" * 64,
            "scope": "synthetic test fixture only",
        },
    }
    return payload, forecast


@pytest.fixture(scope="module")
def engine():
    instance = HybridEngine()
    yield instance
    instance.close()


def evaluate(engine, payload, forecast):
    return assess_request(
        payload, lambda original: forecast, "test-only-hybrid-request", engine=engine
    )


def test_seasonal_offer_uses_actual_schedule_and_same_principal_interest(engine):
    payload, forecast = fixture()
    assessed = evaluate(engine, payload, forecast)
    response = ScoreResponse.model_validate(assessed["result"])
    evidence = assessed["evidence"]["assessment"]
    assert evidence["verdict"] == "affordable"
    assert evidence["tier"] == "p10"
    assert response.recommended_loan.suggested_principal_index > 0
    assert response.loan_terms.annual_rate == 0.24
    assert response.loan_terms.schedule_type == "adaptive"
    assert response.loan_terms.total_interest_index > 0
    assert response.loan_terms.total_repayment_index == pytest.approx(
        response.recommended_loan.suggested_principal_index
        + response.loan_terms.total_interest_index
    )
    offered = evidence["offered"]
    assert offered["actual_within_capacity"]
    assert evidence["comparison"]["annuity_overload_months"] > 0
    assert evidence["comparison"]["offered_overload_months"] == 0
    assert evidence["comparison"]["same_principal"] == offered["principal"]
    assert offered["rows"][-1]["balance"] == pytest.approx(0, abs=0.01)
    for row, budget in zip(offered["rows"], offered["caps"], strict=True):
        assert row["payment"] <= budget + 1.0
        assert row["payment"] == pytest.approx(
            row["principal"] + row["interest"], abs=0.01
        )
    json.dumps(assessed, allow_nan=False)


def test_wide_interval_with_positive_median_is_elevated_risk_not_decline(engine):
    payload, forecast = fixture(median=np.full(12, 150000.0), spread=1000000.0)
    assessed = evaluate(engine, payload, forecast)
    result, evidence = assessed["result"], assessed["evidence"]["assessment"]
    assert evidence["verdict"] == "elevatedrisk_officer"
    assert evidence["tier"] == "p50"
    assert evidence["tiers"]["p10"]["principal"] == 0
    assert result["recommended_loan"]["suggested_principal_index"] > 0
    assert "verdict_elevated_risk" in result["flags"]
    assert result["capacity_score"] > 0
    assert result["confidence"] < 0.3


@pytest.mark.parametrize("requested", [None, 0.0])
def test_sparse_conservative_budget_rejects_tolerance_dust_and_selects_material_offer(
    engine, requested
):
    payload, forecast = fixture(
        median=np.asarray([300000.0] * 3 + [150000.0] * 9),
        spread=300000.0,
        requested=requested,
    )
    assessed = evaluate(engine, payload, forecast)
    result = ScoreResponse.model_validate(assessed["result"])
    assessment = assessed["evidence"]["assessment"]
    conservative = assessment["tiers"]["p10"]
    assert np.count_nonzero(np.asarray(conservative["caps"]) == 0) == 9
    assert conservative["pv_budget"] > 300000
    # Before the fix this budget yielded a 6.16 UZS "affordable" offer solely
    # because its interest and payments fit within the 1 UZS solver tolerance.
    assert conservative["principal"] == 0
    assert conservative["rows"] == []
    assert not conservative["actual_within_capacity"]
    assert assessment["verdict"] == "elevatedrisk_officer"
    assert assessment["tier"] == "p20"
    assert assessment["requested_fit_status"] == "unspecified"
    offered = assessment["offered"]
    assert offered["principal"] > 100000
    assert offered["principal"] >= (MIN_OFFER_SHARE_OF_BUDGET * offered["pv_budget"])
    assert offered["actual_within_capacity"]
    assert assessment["comparison"]["offered_overload_months"] == 0
    assert result.loan_terms.schedule_type == "adaptive"
    assert "verdict_elevated_risk" in result.flags
    assert "verdict_affordable" not in result.flags
    assert result.recommended_loan.suggested_principal_index == offered["principal"]
    assert result.capacity_score == assessment["score"]


def test_explicit_small_principal_is_not_subject_to_offer_materiality_policy(engine):
    payload, forecast = fixture(
        median=np.asarray([300000.0] * 3 + [150000.0] * 9),
        spread=300000.0,
        requested=1.0,
    )
    assessed = evaluate(engine, payload, forecast)
    result = ScoreResponse.model_validate(assessed["result"])
    assessment = assessed["evidence"]["assessment"]
    assert assessment["tiers"]["p10"]["principal"] == 0
    assert assessment["verdict"] == "elevatedrisk_officer"
    assert assessment["tier"] == "p20"
    assert assessment["requested_fit_status"] == "fits_selected_offer"
    assert not assessment["requested_exceeds"]
    offered = assessment["offered"]
    assert (
        offered["principal"] == result.recommended_loan.suggested_principal_index == 1
    )
    assert offered["principal"] < MIN_OFFER_SHARE_OF_BUDGET * offered["pv_budget"]
    assert offered["actual_within_capacity"]
    assert result.loan_terms.total_interest_index > 0
    assert result.loan_terms.total_repayment_index > 1
    assert assessment["comparison"]["offered_overload_months"] == 0


@pytest.mark.parametrize("budget_share,material", [(0.049, False), (0.051, True)])
def test_unrequested_annuity_offer_materiality_uses_discounted_monthly_budget(
    engine, budget_share, material
):
    discounts = (1 + 0.24 / 12) ** -np.arange(1, 13)
    strong_budget = 100000.0
    weak_budget = (
        budget_share
        * strong_budget
        * float(discounts[1:].sum())
        / (float(discounts.sum()) - budget_share * discounts[0])
    )
    caps = np.asarray([weak_budget] + [strong_budget] * 11)
    offer = engine._solve_offer(
        caps, np.full(12, strong_budget), list(range(2025 * 12, 2026 * 12)), False
    )
    theoretical = engine.present_value(weak_budget, 0.24 / 12, 12)
    assert theoretical / offer["pv_budget"] == pytest.approx(budget_share)
    assert (offer["principal"] > 0) is material
    assert offer["actual_within_capacity"] is material
    if material:
        assert offer["principal"] >= MIN_OFFER_SHARE_OF_BUDGET * offer["pv_budget"]
        assert offer["rows"]
    else:
        assert offer["rows"] == []


def test_zero_first_month_budget_cannot_create_main_offer_from_lp_residual(
    engine, monkeypatch
):
    # Synthetic input: low first-season revenue, then stronger months. The
    # median supports repayment but both lower bands start with zero capacity.
    median = np.full(12, 500000.0)
    median[0] = 100000.0
    payload, forecast = fixture(median=median, spread=300000.0)
    native_maximum = engine.max_feasible_principal
    monkeypatch.setattr(
        engine,
        "max_feasible_principal",
        lambda rate, caps: max(native_maximum(rate, caps), 20.0),
    )
    assessed = evaluate(engine, payload, forecast)
    assessment = assessed["evidence"]["assessment"]
    assert assessment["tiers"]["p10"]["caps"][0] == 0
    assert assessment["tiers"]["p20"]["caps"][0] == 0
    assert assessment["tiers"]["p10"]["principal"] == 0
    assert assessment["tiers"]["p20"]["principal"] == 0
    assert assessment["tier"] == "p50"
    assert assessment["verdict"] == "elevatedrisk_officer"
    assert assessed["result"]["recommended_loan"]["suggested_principal_index"] > 0


def test_persistent_decline_sets_main_offer_and_score_zero(engine):
    history = np.geomspace(500000.0, 70000.0, 24)
    payload, forecast = fixture(history=history, median=np.full(12, 150000.0))
    assessed = evaluate(engine, payload, forecast)
    result, assessment = assessed["result"], assessed["evidence"]["assessment"]
    assert assessment["decline_guard"]["triggered"]
    assert assessment["verdict"] == "decline"
    assert result["recommended_loan"]["suggested_principal_index"] == 0
    assert result["capacity_score"] == 0
    assert result["score_band"] == "low"
    assert result["adaptive_schedule"] == []
    assert result["loan_terms"]["total_interest_index"] == 0
    assert "sustained_decline_guard" in result["flags"]


def test_seasonal_decline_guard_compares_same_calendar_months():
    assert not persistent_decline(np.tile(PATTERN, 2))["triggered"]
    declining_seasonal = np.concatenate([PATTERN, PATTERN * 0.65])
    guard = persistent_decline(declining_seasonal)
    assert guard["triggered"]
    assert guard["matched_months"] == 6
    assert guard["median_year_on_year_ratio"] == pytest.approx(0.65)
    assert persistent_decline(np.geomspace(500000.0, 70000.0, 12))["triggered"]


def test_median_negative_month_viability_suppresses_positive_pv_capacity(engine):
    median = np.asarray([1000000.0] * 6 + [40000.0] * 6)
    payload, forecast = fixture(median=median)
    assessed = evaluate(engine, payload, forecast)
    assessment = assessed["evidence"]["assessment"]
    assert assessment["tiers"]["p50"]["principal"] > 0
    assert assessment["median_viability_guard"]["triggered"]
    assert assessment["verdict"] == "decline"
    assert assessed["result"]["recommended_loan"]["suggested_principal_index"] == 0
    assert assessed["result"]["capacity_score"] == 0


def test_invalid_input_and_provider_failures_are_distinct(engine):
    with pytest.raises(HybridInputError) as error:
        assess_request({}, lambda original: {}, "invalid-input", engine=engine)
    assert error.value.code == "invalid_assessment_input"
    payload, forecast = fixture()
    forecast["quantile_levels"] = []
    with pytest.raises(ValueError) as error:
        evaluate(engine, payload, forecast)
    assert not isinstance(error.value, HybridInputError)


def test_nonpositive_median_actual_capacity_declines_and_repeating_seasonal_dip_does_not(
    engine,
):
    assert not persistent_decline(np.tile(PATTERN, 3))["triggered"]
    payload, forecast = fixture(median=np.full(12, 40000.0))
    result = evaluate(engine, payload, forecast)["result"]
    assert "no_actual_median_schedule_capacity" in result["flags"]
    assert result["recommended_loan"]["suggested_principal_index"] == 0
    assert result["capacity_score"] == 0


def test_requested_amount_checks_actual_offered_capacity(engine):
    payload, forecast = fixture(requested=100000000.0)
    assessed = evaluate(engine, payload, forecast)
    assert "requested_amount_exceeds_offered_capacity" in assessed["result"]["flags"]
    assert (
        assessed["evidence"]["assessment"]["requested_fit_status"]
        == "exceeds_selected_capacity"
    )
    assert (
        assessed["result"]["recommended_loan"]["suggested_principal_index"]
        < payload.requested_amount
    )
    small, forecast = fixture(requested=100000.0)
    assessed = evaluate(engine, small, forecast)
    result = assessed["result"]
    assert (
        assessed["evidence"]["assessment"]["requested_fit_status"]
        == "fits_selected_offer"
    )
    assert result["recommended_loan"]["suggested_principal_index"] == 100000.0
    assert (
        sum(row["installment_index"] for row in result["adaptive_schedule"]) > 100000.0
    )
    declining, forecast = fixture(
        history=np.geomspace(500000.0, 70000.0, 24), requested=100000.0
    )
    assessed = evaluate(engine, declining, forecast)
    assert (
        assessed["evidence"]["assessment"]["requested_fit_status"]
        == "declined_by_guard"
    )
    assert assessed["evidence"]["assessment"]["requested_exceeds"]
    assert "requested_amount_exceeds_offered_capacity" in assessed["result"]["flags"]
    assert assessed["result"]["recommended_loan"]["suggested_principal_index"] == 0
    unspecified, forecast = fixture(requested=0.0)
    assessed = evaluate(engine, unspecified, forecast)
    assert assessed["evidence"]["assessment"]["requested_fit_status"] == "unspecified"
    assert not assessed["evidence"]["assessment"]["requested_exceeds"]


def test_six_month_annuity_fallback_and_insufficient_history_suppression(engine):
    payload, forecast = fixture(
        history=np.full(6, 150000.0), median=np.full(12, 150000.0)
    )
    result = evaluate(engine, payload, forecast)["result"]
    assert result["loan_terms"]["schedule_type"] == "annuity"
    assert result["recommended_loan"]["suggested_principal_index"] > 0
    payload, forecast = fixture(
        history=np.full(3, 150000.0), median=np.full(12, 150000.0)
    )
    result = evaluate(engine, payload, forecast)["result"]
    assert result["recommended_loan"]["suggested_principal_index"] == 0
    assert "insufficient_observed_history" in result["flags"]


def test_short_history_calibration_scope_is_explicit_and_offer_remains_zero(engine):
    payload, forecast = fixture(
        history=np.full(2, 150000.0), median=np.full(12, 150000.0)
    )
    forecast["provenance"]["uncertainty_support"] = "below_calibration_minimum_3_months"
    forecast["provenance"]["effective_revenue_component"] = "current"
    forecast["provenance"]["short_history_fallback"] = (
        "incumbent_below_upgrade_minimum_3_months"
    )
    assessed = evaluate(engine, payload, forecast)
    result = assessed["result"]
    assert "below_calibration_minimum_3_months" in result["flags"]
    assert "short_history_incumbent_revenue_fallback" in result["flags"]
    assert result["recommended_loan"]["suggested_principal_index"] == 0
    assert any(
        "no measured coverage" in text for text in result["explanation"]["advisory"]
    )
    assert (
        assessed["evidence"]["revenue_provider_identity"]["uncertainty_support"]
        == "below_calibration_minimum_3_months"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["history_inflow"].__setitem__(0, 1.0),
        lambda value: value["months"].__setitem__(0, "2025-02"),
        lambda value: value["revenue_grid"][0].__setitem__(10, float("nan")),
        lambda value: value.update(actual=[100] * 12),
        lambda value: value.update(expense_policy="synthetic_trained"),
    ],
)
def test_provider_contract_rejects_wrong_history_labels_calendar_and_financial_provenance(
    engine, mutation
):
    payload, forecast = fixture()
    mutation(forecast)
    with pytest.raises(ValueError):
        evaluate(engine, payload, forecast)


def test_forecast_and_model_bytes_unchanged_and_synthetic_backtest_retains_losses(
    engine,
):
    payload, forecast = fixture()
    original = copy.deepcopy(forecast)
    assessed = evaluate(engine, payload, forecast)
    assert forecast == original
    assessment = assessed["evidence"]["assessment"]
    true_seasonal = PATTERN - 50000
    favorable = compare_actual_surplus(assessment, true_seasonal)
    assert favorable["offered"]["overload_months"] == 0
    assert favorable["annuity"]["overload_months"] > 0
    unexpected_flat = compare_actual_surplus(
        assessment, np.full(12, np.mean(true_seasonal))
    )
    assert (
        unexpected_flat["offered"]["overload_months"]
        > unexpected_flat["annuity"]["overload_months"]
    )
    assert (
        engine.identity["model_artifact_sha256"]
        == "51091e827f0b9d768878bd8e414e2c10dd18c7e3dee884acb3680b722bfa8d1a"
    )
