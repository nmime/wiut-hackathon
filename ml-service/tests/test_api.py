import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from capacity_ml.api import MAX_BODY_BYTES, canonical_hash, create_app
from capacity_ml.schemas import ScoreResponse


def test_live_inference_audited_and_invalid_attempts_persist(
    model, request_payload, tmp_path
):
    audit_path = tmp_path / "audit.jsonl"
    with TestClient(create_app(audit_path=audit_path)) as client:
        health = client.get("/health").json()
        assert health["local_inference"] is True
        assert health["synthetic_training_only"] is False
        assert health["public_training_targets"] == 8880
        assert health["public_transfer_weight"] == model.transfer_weight
        assert health["serving_mode"] == model.selection["serving_mode"]
        raw = json.dumps(request_payload).encode()
        response = client.post(
            "/score",
            content=raw,
            headers={
                "content-type": "application/json",
                "x-request-id": "nest-correlated-request",
            },
        )
        assert response.status_code == 200
        result = ScoreResponse.model_validate(response.json())
        assert (
            result.request_id
            == response.headers["x-request-id"]
            == "nest-correlated-request"
        )
        invalid = client.post("/score", json={**request_payload, "extra": True})
        assert invalid.status_code == 422
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert [event["event"] for event in events] == [
        "assessment_requested",
        "assessment_completed",
        "assessment_requested",
        "assessment_failed",
    ]
    completed = events[1]
    assert completed["result"] == response.json()
    assert completed["response_hash"] == canonical_hash(response.json())
    assert completed["input_hash"] == hashlib.sha256(raw).hexdigest()
    assert completed["model_version"] == result.model_version
    assert "transactions" not in completed


def test_request_ingestion_bound_for_declared_and_streamed_bodies(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    with TestClient(create_app(audit_path=audit_path)) as client:
        declared = client.post(
            "/score", content=b"{}", headers={"content-length": str(MAX_BODY_BYTES + 1)}
        )
        assert declared.status_code == 413
        streamed = client.post(
            "/score",
            content=iter(
                [b"x" * (MAX_BODY_BYTES // 2), b"x" * (MAX_BODY_BYTES // 2), b"x"]
            ),
        )
        assert streamed.status_code == 413
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert len(events) == 4
    assert events[1]["status"] == events[3]["status"] == 413
    assert events[0]["input_hash_scope"] == "prefix"


def test_unavailable_audit_never_releases_recommendation(
    request_payload, tmp_path, monkeypatch
):
    application = create_app(audit_path=tmp_path / "audit.jsonl")
    with TestClient(application) as client:

        def unavailable(_):
            raise OSError("simulated full local disk")

        monkeypatch.setattr(application.state.audit, "append", unavailable)
        response = client.post("/score", json=request_payload)
        assert response.status_code == 503
        assert "recommended_loan" not in response.json()


def test_missing_model_fails_startup_without_fallback(tmp_path):
    with pytest.raises(RuntimeError, match="Run.*capacity_ml.train"):
        with TestClient(
            create_app(
                model_path=tmp_path / "missing.joblib",
                audit_path=tmp_path / "audit.jsonl",
            )
        ):
            pass
