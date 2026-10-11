"""Final runtime audit and failure behaviour with disclosed synthetic inputs."""

import hashlib
import json

import numpy as np
import pytest
from capacity_ml.api import MAX_BODY_BYTES, canonical_hash
from capacity_ml.forecasting import aggregate
from fastapi.testclient import TestClient
from final_model.api import create_app
from teammate_bridge.schemas import ScoreResponse


class SyntheticTestProvider:
    identity = {"test_only": True, "model_artifact_sha256": "1" * 64}
    health = {"revenue_candidate": "synthetic_runtime_fixture", "test_only": True}

    def __call__(self, payload):
        history = aggregate(payload)
        mean = float(np.mean(history.inflow[-12:]))
        costs = float(np.mean(history.outflow[-12:]))
        return {
            "months": [
                f"{month // 12:04d}-{month % 12 + 1:02d}"
                for month in range(history.forecast_start, history.forecast_start + 12)
            ],
            "median": [mean] * 12,
            "revenue_grid": np.tile(mean * np.linspace(0.7, 1.3, 99), (12, 1)).tolist(),
            "quantile_levels": (np.arange(1, 100) / 100).tolist(),
            "observed_outflow_projection": [costs] * 12,
            "history_months": [
                f"{int(month) // 12:04d}-{int(month) % 12 + 1:02d}"
                for month in history.months
            ],
            "history_inflow": history.inflow.tolist(),
            "history_outflow": history.outflow.tolist(),
            "expense_policy": "observed_cost_projection",
            "provenance": {
                "revenue_model_version": "synthetic-test-provider",
                "revenue_candidate": "synthetic_runtime_fixture",
                "real_training_targets": 0,
                "model_artifact_sha256": "1" * 64,
                "calibration_sha256": "2" * 64,
            },
        }


@pytest.fixture
def payload():
    transactions = []
    for offset in range(24):
        month_id = 2024 * 12 + 9 + offset
        prefix = f"{month_id // 12:04d}-{month_id % 12 + 1:02d}"
        for direction, amount in (("in", 10_000_000.0), ("out", 2_000_000.0)):
            transactions.append(
                {
                    "ts": f"{prefix}-01T12:00:00Z",
                    "direction": direction,
                    "channel": "card" if direction == "in" else "transfer",
                    "amount_index": amount,
                }
            )
    return {
        "business_id": "synthetic-runtime-test",
        "as_of_date": "2026-09-30",
        "transactions": transactions,
        "requested_amount": None,
        "currency": "UZS",
    }


def application(audit_path, provider=None):
    return create_app(
        audit_path=audit_path,
        provider_factory=lambda _path: provider or SyntheticTestProvider(),
    )


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_validated_result_and_financial_evidence_are_durable_before_release(
    payload, tmp_path
):
    path = tmp_path / "audit.jsonl"
    raw = json.dumps(payload).encode()
    with TestClient(application(path)) as client:
        health = client.get("/health").json()
        assert health["identity_scope"] == "complete_local_model_assembly"
        assert health["annual_interest_rate"] == 0.24
        assert health["model_artifact_sha256"] == canonical_hash(
            health["component_identity"]
        )
        response = client.post(
            "/score",
            content=raw,
            headers={"content-type": "application/json", "x-request-id": "final-audit"},
        )
        assert response.status_code == 200
        result = ScoreResponse.model_validate(response.json())
        assert result.model_version == health["model_version"]
        assert result.request_id == response.headers["x-request-id"] == "final-audit"
        assert result.loan_terms.annual_rate == 0.24
        assert result.loan_terms.total_interest_index > 0
        audit = events(path)
        assert [row["event"] for row in audit] == [
            "assessment_requested",
            "assessment_completed",
        ]
        assert all(
            row["model_artifact_sha256"] == health["model_artifact_sha256"]
            for row in audit
        )
        completed = audit[-1]
        assert completed["input_hash"] == hashlib.sha256(raw).hexdigest()
        assert completed["response_hash"] == canonical_hash(response.json())
        assert completed["result"] == response.json()
        assert completed["component_identity"] == health["component_identity"]
        evidence = completed["financial_evidence"]
        assert np.shape(evidence["revenue_forecast"]["grid"]) == (12, 99)
        assert evidence["assessment"]["offered"]["actual_within_capacity"] is True
        assert evidence["assessment"]["comparison"]["same_annual_rate"] == 0.24
        assert "transactions" not in completed


def test_invalid_and_oversized_requests_persist_failed_attempts(tmp_path, payload):
    path = tmp_path / "invalid.jsonl"
    with TestClient(application(path)) as client:
        invalid = client.post("/score", json={**payload, "extra": True})
        assert invalid.status_code == 422
        oversized = client.post(
            "/score", content=b"{}", headers={"content-length": str(MAX_BODY_BYTES + 1)}
        )
        assert oversized.status_code == 413
        streamed = client.post("/score", content=iter([b"x" * MAX_BODY_BYTES, b"x"]))
        assert streamed.status_code == 413
    audit = events(path)
    assert len(audit) == 6
    assert [row["status"] for row in audit if "status" in row] == [422, 413, 413]
    assert audit[2]["input_hash_scope"] == "prefix"


def test_audit_failure_releases_no_result(payload, tmp_path, monkeypatch):
    app = application(tmp_path / "unavailable.jsonl")
    with TestClient(app) as client:

        def unavailable(_entry):
            raise OSError("Test-only unavailable audit volume")

        monkeypatch.setattr(app.state.audit, "append", unavailable)
        response = client.post("/score", json=payload)
        assert response.status_code == 503
        assert "recommended_loan" not in response.json()


def test_invalid_provider_contract_fails_without_fallback(payload, tmp_path):
    class InvalidProvider(SyntheticTestProvider):
        def __call__(self, request):
            result = super().__call__(request)
            result["revenue_grid"][0][0] = float("nan")
            return result

    path = tmp_path / "malformed-provider.jsonl"
    with TestClient(application(path, InvalidProvider())) as client:
        response = client.post("/score", json=payload)
        assert response.status_code == 500
        assert "recommended_loan" not in response.json()
    assert events(path)[-1]["event"] == "assessment_failed"


def test_response_is_validated_before_release(payload, tmp_path, monkeypatch):
    from hybrid import scorer

    original = scorer.assess_request

    def broken(*args, **kwargs):
        assessment = original(*args, **kwargs)
        assessment["result"]["loan_terms"]["total_interest_index"] = 0.0
        return assessment

    monkeypatch.setattr(scorer, "assess_request", broken)
    path = tmp_path / "malformed-result.jsonl"
    with TestClient(application(path)) as client:
        response = client.post("/score", json=payload)
        assert response.status_code == 500
        assert "recommended_loan" not in response.json()
    assert events(path)[-1]["event"] == "assessment_failed"


def test_missing_final_bundle_fails_startup_without_retraining(tmp_path):
    with pytest.raises(RuntimeError, match="No model is retrained"):
        with TestClient(
            create_app(
                bundle_path=tmp_path / "missing", audit_path=tmp_path / "audit.jsonl"
            )
        ):
            pass


def test_loaded_identity_is_fixed_after_provider_metadata_changes(payload, tmp_path):
    provider = SyntheticTestProvider()
    provider.identity = dict(provider.identity)
    provider.health = dict(provider.health)
    with TestClient(application(tmp_path / "identity.jsonl", provider)) as client:
        before = client.get("/health").json()
        provider.identity["model_artifact_sha256"] = "9" * 64
        provider.health["revenue_candidate"] = "changed-after-startup"
        assert client.get("/health").json() == before
        response = client.post("/score", json=payload)
        assert response.status_code == 200
        assert response.json()["model_version"] == before["model_version"]


@pytest.mark.parametrize("partial_only", [False, True])
def test_midmonth_forecasts_begin_after_assessment_and_partial_only_has_no_loan(
    payload, tmp_path, partial_only
):
    current = {
        "ts": "2026-10-01T12:00:00Z",
        "direction": "in",
        "channel": "card",
        "amount_index": 10_000_000.0,
    }
    payload["as_of_date"] = "2026-10-11"
    payload["transactions"] = (
        [current] if partial_only else [*payload["transactions"], current]
    )
    path = tmp_path / "midmonth.jsonl"
    with TestClient(application(path)) as client:
        response = client.post("/score", json=payload)
        assert response.status_code == 200
        result = ScoreResponse.model_validate(response.json())
        if partial_only:
            assert result.recommended_loan.suggested_principal_index == 0
            assert result.adaptive_schedule == []
    evidence = events(path)[-1]["financial_evidence"]
    assert evidence["revenue_forecast"]["months"][0] == "2026-11"
