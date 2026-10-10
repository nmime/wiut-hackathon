import os

import pytest

from capacity_ml.forecasting import ForecastModel
from capacity_ml.schemas import ScoreRequest


@pytest.fixture(scope="session")
def model():
    try:
        return ForecastModel.load(
            os.environ.get("ML_MODEL_PATH", "runtime/model.joblib")
        )
    except (OSError, ValueError) as error:
        pytest.fail(f"Train the local artifact before testing: {error}")


@pytest.fixture
def request_payload():
    transactions = []
    for offset in range(24):
        year, month = 2024 + offset // 12, offset % 12 + 1
        for direction, amount in (("in", 100 + 2 * offset), ("out", 60 + offset)):
            transactions.append(
                {
                    "ts": f"{year:04d}-{month:02d}-15T12:00:00Z",
                    "direction": direction,
                    "channel": "qr" if direction == "in" else "transfer",
                    "amount_index": amount,
                }
            )
    return {
        "business_id": "synthetic-test-input",
        "as_of_date": "2025-12-31",
        "transactions": transactions,
        "requested_amount": None,
        "currency": "UZS",
    }


@pytest.fixture
def score_request_input(request_payload):
    return ScoreRequest.model_validate(request_payload)
