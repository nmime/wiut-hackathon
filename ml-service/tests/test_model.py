import copy

import joblib
import numpy as np
import pytest

from capacity_ml.forecasting import (
    ForecastModel,
    aggregate,
    feature_matrix,
    month_id,
    seasonal_forecast,
)
from capacity_ml.generator import SEED, TEST_COUNT, generate_business
from capacity_ml.schemas import ScoreRequest
from capacity_ml.scoring import capacity_plan, history_statistics, score_request


def test_deterministic_generation_and_future_time_split():
    first = generate_business("test", 3)
    repeated = generate_business("test", 3)
    np.testing.assert_array_equal(first.future_net, repeated.future_net)
    assert first.transactions == repeated.transactions
    request = first.request()
    assert all(row.ts[:10] <= request.as_of_date for row in request.transactions)
    assert int(first.months[first.cutoff]) > int(first.months[first.cutoff - 1])
    realised = []
    for month in first.months[first.cutoff :]:
        month_prefix = f"{month // 12:04d}-{month % 12 + 1:02d}"
        events = [row for row in first.transactions if row.ts.startswith(month_prefix)]
        realised.append(
            sum(
                row.amount_index if row.direction == "in" else -row.amount_index
                for row in events
            )
        )
    np.testing.assert_allclose(realised, first.future_net)


def test_selection_excludes_test_businesses(model):
    training = set(model.selection["train_ids"])
    validation = set(model.selection["validation_ids"])
    test_ids = {f"synthetic-test-{position:04d}" for position in range(TEST_COUNT)}
    assert not training & validation
    assert not training & test_ids
    assert not validation & test_ids
    assert model.selection["test_used_for_selection"] is False
    maes = model.selection["validation_mae_index"]
    assert model.selection["selected_candidate"] == min(maes, key=maes.get)
    assert model.selection["seed"] == SEED


def test_predictions_deterministic_but_respond_to_changed_cashflow(
    model, request_payload
):
    original_request = ScoreRequest.model_validate(request_payload)
    first = score_request(original_request, model, "same-request")
    repeated = score_request(original_request, model, "same-request")
    assert first == repeated
    for row in request_payload["transactions"]:
        if row["direction"] == "out":
            row["amount_index"] *= 3
    changed = score_request(ScoreRequest.model_validate(request_payload), model)
    assert (
        changed.seasonality.monthly_forecast_index
        != first.seasonality.monthly_forecast_index
    )
    assert changed.capacity_score < first.capacity_score
    assert changed.recommended_loan.suggested_principal_index == 0
    assert changed.adaptive_schedule == []


@pytest.mark.parametrize("scale", [1e-6, 0.001, 1e6])
def test_amount_index_scale_invariance(model, request_payload, scale):
    original = score_request(ScoreRequest.model_validate(request_payload), model)
    scaled_payload = copy.deepcopy(request_payload)
    for row in scaled_payload["transactions"]:
        row["amount_index"] *= scale
    scaled = score_request(ScoreRequest.model_validate(scaled_payload), model)
    assert scaled.capacity_score == pytest.approx(original.capacity_score)
    assert scaled.confidence == pytest.approx(original.confidence)
    assert scaled.recommended_loan.suggested_principal_index == pytest.approx(
        original.recommended_loan.suggested_principal_index * scale
    )
    np.testing.assert_allclose(
        scaled.seasonality.monthly_forecast_index,
        np.asarray(original.seasonality.monthly_forecast_index) * scale,
        rtol=1e-8,
    )


def test_schedule_caps_fixed_debt_and_factor_decomposition(model, score_request_input):
    response = score_request(score_request_input, model)
    history = aggregate(score_request_input)
    forecast = np.asarray(response.seasonality.monthly_forecast_index)
    plan = capacity_plan(history, forecast)
    assert response.recommended_loan.suggested_principal_index > 0
    payments = np.asarray([row.installment_index for row in response.adaptive_schedule])
    assert len(payments) == response.recommended_loan.suggested_term_months == 12
    assert all(
        row.month_offset == i + 1 for i, row in enumerate(response.adaptive_schedule)
    )
    assert np.all(payments >= 0)  # 0% interest floor means no negative amortization.
    assert np.all(payments <= plan["capacities"] + 1e-10)
    assert np.sum(payments) == pytest.approx(
        response.recommended_loan.suggested_principal_index
    )
    assert 50 + sum(
        factor.weight for factor in response.explanation.top_factors
    ) == pytest.approx(response.capacity_score)
    assert "0% interest" in response.recommended_loan.rationale


def test_uzs_request_cannot_cap_indexed_principal(model, score_request_input):
    original = score_request(score_request_input, model)
    requested = score_request(
        score_request_input.model_copy(update={"requested_amount": 0.0}), model
    )
    assert requested.recommended_loan == original.recommended_loan
    assert "currency_conversion_missing" in requested.flags


def test_sparse_calendar_partial_cutoff_and_offsets(request_payload):
    request_payload["transactions"] = [
        {
            **request_payload["transactions"][0],
            "ts": "2025-01-01T00:00:00+05:00",
            "amount_index": 50,
        },
        {
            **request_payload["transactions"][0],
            "ts": "2025-03-01T00:00:00",
            "amount_index": 30,
        },
        {
            **request_payload["transactions"][0],
            "ts": "2025-04-10T00:00:00Z",
            "amount_index": 999,
        },
    ]
    request_payload["as_of_date"] = "2025-04-20"
    history = aggregate(ScoreRequest.model_validate(request_payload))
    np.testing.assert_array_equal(history.inflow, [50, 0, 30])
    assert history.forecast_start == month_id(2025, 5)
    assert history.partial_month_excluded is True
    assert feature_matrix(history)[0][10] == pytest.approx(2 / 12)
    # First forecast is May, not April/last-transaction-relative.
    expected = np.full(12, 80 / 3)
    expected[8:11] = [50, 0, 30]  # January/February/March, preserving the gap.
    np.testing.assert_array_equal(seasonal_forecast(history), expected)


def test_cold_start_partial_only_and_stale_history_no_loan(model, request_payload):
    short = copy.deepcopy(request_payload)
    short["transactions"] = [
        row for row in short["transactions"] if row["ts"].startswith("2025-12")
    ]
    short["as_of_date"] = "2025-12-20"
    result = score_request(ScoreRequest.model_validate(short), model)
    assert result.confidence <= 0.03
    assert "partial_history_only" in result.flags
    assert "partial_month_excluded" not in result.flags
    assert result.recommended_loan.suggested_principal_index == 0
    stale = score_request(
        ScoreRequest.model_validate({**request_payload, "as_of_date": "2026-12-31"}),
        model,
    )
    assert stale.confidence < 0.1
    assert "stale_history_no_loan" in stale.flags
    assert stale.recommended_loan.suggested_principal_index == 0


def test_inflow_trend_separate_from_surplus_trend(request_payload):
    for i, row in enumerate(request_payload["transactions"]):
        row["amount_index"] = 100 if row["direction"] == "in" else 20 + i
    statistics = history_statistics(
        aggregate(ScoreRequest.model_validate(request_payload))
    )
    assert statistics["trend"] == "stable"
    assert statistics["relative_trend"] < 0


def test_stale_or_corrupt_artifact_rejected(model, tmp_path):
    corrupted = tmp_path / "corrupt.joblib"
    joblib.dump({"not": "a forecast model"}, corrupted)
    with pytest.raises(ValueError, match="Unsupported"):
        ForecastModel.load(corrupted)
    stale = copy.deepcopy(model)
    stale.selection["source_sha256"] = "obsolete"
    stale.save(tmp_path / "stale.joblib")
    with pytest.raises(ValueError, match="Stale"):
        ForecastModel.load(tmp_path / "stale.joblib")
