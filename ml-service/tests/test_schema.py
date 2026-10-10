import copy
import math

import pytest
from pydantic import ValidationError

from capacity_ml.schemas import ScoreRequest, ScoreResponse
from capacity_ml.scoring import score_request


@pytest.mark.parametrize("value", [True, "20", math.inf, math.nan, -1, 0, 1e12 + 1])
def test_reject_invalid_transaction_amounts(request_payload, value):
    request_payload["transactions"][0]["amount_index"] = value
    with pytest.raises(ValidationError):
        ScoreRequest.model_validate(request_payload)


@pytest.mark.parametrize("value", [False, "10", math.inf, math.nan, -1, 1e15 + 1])
def test_reject_invalid_requested_currency_amount(request_payload, value):
    request_payload["requested_amount"] = value
    with pytest.raises(ValidationError):
        ScoreRequest.model_validate(request_payload)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2024-02-30T12:00:00Z",
        "2024-01-01",
        "2024-01-01T24:00:00Z",
        "2026-01-01T00:00:00Z",
        "2024-01-01T12:00:00+30:00",
    ],
)
def test_reject_invalid_dates_and_future_events(request_payload, timestamp):
    request_payload["transactions"][0]["ts"] = timestamp
    with pytest.raises(ValidationError):
        ScoreRequest.model_validate(request_payload)


@pytest.mark.parametrize("extra_target", ["request", "transaction"])
def test_no_unknown_fields(request_payload, extra_target):
    target = (
        request_payload
        if extra_target == "request"
        else request_payload["transactions"][0]
    )
    target["secret"] = "unexpected"
    with pytest.raises(ValidationError):
        ScoreRequest.model_validate(request_payload)


def test_history_count_and_calendar_bounds(request_payload):
    for transactions in ([], [request_payload["transactions"][0]] * 20001):
        invalid = {**request_payload, "transactions": transactions}
        with pytest.raises(ValidationError):
            ScoreRequest.model_validate(invalid)
    for assessment_date in ("0000-01-01", "2025-02-29", "9999-01-01"):
        with pytest.raises(ValidationError):
            ScoreRequest.model_validate(
                {**request_payload, "as_of_date": assessment_date}
            )
    request_payload["transactions"][0]["ts"] = "2000-01-01T00:00:00Z"
    with pytest.raises(ValidationError, match="240 months"):
        ScoreRequest.model_validate(request_payload)


def test_response_rejects_unknown_nonfinite_and_bad_schedule(
    model, score_request_input
):
    valid = score_request(score_request_input, model).model_dump()
    for mutation in (
        "extra",
        "nan",
        "overlapping_months",
        "noncontiguous",
        "missing_schedule",
    ):
        changed = copy.deepcopy(valid)
        if mutation == "extra":
            changed["approved"] = True
        elif mutation == "nan":
            changed["seasonality"]["monthly_forecast_index"][0] = math.nan
        elif mutation == "overlapping_months":
            changed["seasonality"]["weak_months"] = [1]
            changed["seasonality"]["strong_months"] = [1]
        elif mutation == "noncontiguous":
            changed["adaptive_schedule"][0]["month_offset"] = 2
        else:
            changed["adaptive_schedule"] = []
        with pytest.raises(ValidationError):
            ScoreResponse.model_validate(changed)
