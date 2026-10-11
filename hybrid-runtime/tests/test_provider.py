"""Actual frozen provider integration; borrower fixtures are synthetic only.

The public-series check uses a real aggregate's observed history pattern mapped
to a mean-100 test amount index (1 test index = 1 test UZS). It establishes saved
forecast reproducibility, not a real borrower currency conversion or accuracy.
Future labels are not accessed, and no model/calibration is fitted by these tests.
"""

import calendar
import json
from pathlib import Path

import numpy as np
import pytest
from capacity_ml.schemas import ScoreRequest
from final_model.provider import load_provider
from hybrid.scorer import HybridEngine, assess_request
from teammate_bridge.schemas import ScoreResponse

ROOT = Path(__file__).resolve().parents[2]
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


def request(history, *, as_of_date="2024-12-31", outflow=50000.0, requested=None):
    year, month, _ = map(int, as_of_date.split("-"))
    last = year * 12 + month - 1
    transactions = []
    for month_id, inflow in zip(
        range(last - len(history) + 1, last + 1), history, strict=True
    ):
        label = f"{month_id // 12:04d}-{month_id % 12 + 1:02d}"
        transactions.append(
            {
                "ts": label + "-05T12:00:00+05:00",
                "direction": "in",
                "channel": "card",
                "amount_index": float(inflow),
            }
        )
        if outflow > 0:
            transactions.append(
                {
                    "ts": label + "-06T12:00:00+05:00",
                    "direction": "out",
                    "channel": "transfer",
                    "amount_index": float(outflow),
                }
            )
    return ScoreRequest.model_validate(
        {
            "business_id": "test-only-actual-provider",
            "as_of_date": as_of_date,
            "currency": "UZS",
            "requested_amount": requested,
            "transactions": transactions,
        }
    )


@pytest.fixture(scope="module")
def provider():
    return load_provider(ROOT / "ml-service/final_model/artifacts")


@pytest.fixture(scope="module")
def engine():
    instance = HybridEngine()
    yield instance
    instance.close()


@pytest.mark.parametrize(
    "count,cutoff,expected_count,partial_only",
    [
        (1, "2024-12-31", 1, False),
        (2, "2024-12-31", 2, False),
        (24, "2024-12-11", 23, False),
        (1, "2024-12-11", 1, True),
    ],
)
def test_actual_provider_partial_and_short_calendar_contract(
    provider, engine, count, cutoff, expected_count, partial_only
):
    payload = request(np.full(count, 150000.0), as_of_date=cutoff)
    forecast = provider(payload)
    assert forecast["months"] == [f"2025-{month:02d}" for month in range(1, 13)]
    assert len(forecast["history_months"]) == expected_count
    assert forecast["provenance"]["partial_only"] is partial_only
    assessed = assess_request(payload, provider, "test-only-calendar", engine=engine)
    ScoreResponse.model_validate(assessed["result"])
    if expected_count < 6:
        assert assessed["result"]["recommended_loan"]["suggested_principal_index"] == 0
        assert "verdict_decline" in assessed["result"]["flags"]
    if expected_count < 3:
        assert "below_calibration_minimum_3_months" in assessed["result"]["flags"]


def test_actual_provider_seasonal_positive_median_is_not_declined_for_width(
    provider, engine
):
    payload = request(np.tile(PATTERN, 2))
    assessed = assess_request(payload, provider, "test-only-seasonal", engine=engine)
    assessment = assessed["evidence"]["assessment"]
    assert np.all(np.asarray(assessment["median_surplus"]) > 0)
    assert not assessment["decline_guard"]["triggered"]
    assert assessment["verdict"] in {"affordable", "elevatedrisk_officer"}
    assert assessed["result"]["recommended_loan"]["suggested_principal_index"] > 0
    assert assessed["result"]["loan_terms"]["annual_rate"] == 0.24
    assert assessment["offered"]["actual_within_capacity"]
    assert assessment["comparison"]["offered_overload_months"] == 0


def test_actual_provider_decline_guard_suppresses_requested_main_loan(provider, engine):
    payload = request(np.geomspace(500000.0, 70000.0, 24), requested=100000.0)
    assessed = assess_request(payload, provider, "test-only-decline", engine=engine)
    assessment = assessed["evidence"]["assessment"]
    assert assessment["decline_guard"]["triggered"]
    assert assessment["verdict"] == "decline"
    assert assessment["requested_fit_status"] == "declined_by_guard"
    assert assessed["result"]["recommended_loan"]["suggested_principal_index"] == 0
    assert assessed["result"]["capacity_score"] == 0
    assert assessed["result"]["adaptive_schedule"] == []


def test_loaded_current_point_reproduces_one_saved_real_history_pattern(provider):
    document = json.loads(
        (ROOT / "ml-service/reports/revenue-upgrade-fresh-predictions.json").read_text()
    )
    row = document["cases"][0]
    observed = np.asarray(row["inflow"], dtype=float)
    history_scale = float(np.mean(observed[-12:]))
    # Match the frozen fresh-evaluation normalization operation order exactly.
    normalized = observed * (100 / history_scale)
    expected = np.asarray(row["predictions"]["current"]) / history_scale * 100
    last = row["forecast_start"] - 1
    year, month = last // 12, last % 12 + 1
    cutoff = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    payload = request(normalized, as_of_date=cutoff, outflow=0.0)
    actual = provider(payload)
    native = provider(request(observed, as_of_date=cutoff, outflow=0.0))
    np.testing.assert_allclose(
        native["median"], row["predictions"]["current"], rtol=1e-14, atol=1e-9
    )
    np.testing.assert_array_equal(
        np.asarray(actual["median"]) * (history_scale / 100),
        row["predictions"]["current"],
    )
    assert actual["provenance"]["effective_revenue_component"] == "current"
    assert actual["history_months"] == [
        f"{month // 12:04d}-{month % 12 + 1:02d}" for month in row["months"]
    ]
    np.testing.assert_allclose(actual["median"], expected, rtol=1e-12, atol=1e-10)
    with_costs = provider(request(normalized, as_of_date=cutoff, outflow=20.0))
    np.testing.assert_array_equal(actual["median"], with_costs["median"])
