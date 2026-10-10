import hashlib
import json
import os
import shutil
from pathlib import Path

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
        with Path(os.environ.get("ML_MODEL_PATH", "runtime/model.joblib")).open(
            "rb"
        ) as artifact:
            expected_artifact_sha256 = hashlib.file_digest(
                artifact, "sha256"
            ).hexdigest()
        assert health["model_artifact_sha256"] == expected_artifact_sha256
        assert health["local_inference"] is True
        assert health["synthetic_training_only"] is False
        assert (
            health["public_training_targets"]
            == model.public_revenue_model.metadata["training_examples"]
        )
        assert health["public_transfer_weight"] == model.transfer_weight
        assert health["serving_mode"] == model.selection["serving_mode"]
        assert health["real_revenue_estimator_used"] == bool(
            model.transfer_weight
            and model.public_revenue_model.metadata["selected_uses_trained_estimator"]
        )
        assert {
            source.get("provider") for source in health["public_training_sources"]
        } >= {"abs", "statcan"}
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
    assert all(
        event["model_artifact_sha256"] == expected_artifact_sha256 for event in events
    )
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


@pytest.mark.parametrize("path_change", ["replace", "delete"])
def test_loaded_artifact_identity_survives_disk_path_changes(
    model, request_payload, tmp_path, path_change
):
    model_path = tmp_path / "loaded.joblib"
    audit_path = tmp_path / "loaded-artifact-audit.jsonl"
    shutil.copyfile(os.environ.get("ML_MODEL_PATH", "runtime/model.joblib"), model_path)
    with model_path.open("rb") as artifact:
        expected_sha256 = hashlib.file_digest(artifact, "sha256").hexdigest()
    with TestClient(create_app(model_path=model_path, audit_path=audit_path)) as client:
        initial_health = client.get("/health").json()
        assert initial_health["model_artifact_sha256"] == expected_sha256
        before = client.post(
            "/score",
            json=request_payload,
            headers={"x-request-id": "artifact-before-change"},
        )
        assert before.status_code == 200
        if path_change == "delete":
            model_path.unlink()
        else:
            replacement = tmp_path / "replacement.joblib"
            replacement.write_bytes(b"Not the artifact loaded into this application")
            replacement.replace(model_path)
            assert (
                hashlib.sha256(model_path.read_bytes()).hexdigest() != expected_sha256
            )
        assert client.get("/health").json() == initial_health
        after = client.post(
            "/score",
            json=request_payload,
            headers={"x-request-id": "artifact-after-change"},
        )
        assert after.status_code == 200
        results = [
            ScoreResponse.model_validate(reply.json()) for reply in (before, after)
        ]
        assert all(result.model_version == model.version for result in results)
        assert results[0].model_dump(exclude={"request_id"}) == results[1].model_dump(
            exclude={"request_id"}
        )
        rejected = client.post("/score", json={**request_payload, "extra": True})
        assert rejected.status_code == 422
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert [event["event"] for event in events] == [
        "assessment_requested",
        "assessment_completed",
        "assessment_requested",
        "assessment_completed",
        "assessment_requested",
        "assessment_failed",
    ]
    assert all(event["model_artifact_sha256"] == expected_sha256 for event in events)
    assert all(event["model_version"] == model.version for event in events)


def test_startup_hashes_and_loads_the_same_open_artifact(
    model, request_payload, tmp_path, monkeypatch
):
    model_path = tmp_path / "startup.joblib"
    audit_path = tmp_path / "startup-audit.jsonl"
    shutil.copyfile(os.environ.get("ML_MODEL_PATH", "runtime/model.joblib"), model_path)
    expected_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
    replacement = tmp_path / "replacement.joblib"
    replacement.write_bytes(b"A different file now occupies the configured path")
    file_digest = hashlib.file_digest

    def digest_then_replace(artifact, algorithm):
        digest = file_digest(artifact, algorithm)
        replacement.replace(model_path)
        return digest

    monkeypatch.setattr("capacity_ml.api.hashlib.file_digest", digest_then_replace)
    with TestClient(create_app(model_path=model_path, audit_path=audit_path)) as client:
        health = client.get("/health").json()
        assert health["model_artifact_sha256"] == expected_sha256
        assert health["model_version"] == model.version
        assert hashlib.sha256(model_path.read_bytes()).hexdigest() != expected_sha256
        response = client.post("/score", json=request_payload)
        assert response.status_code == 200
        assert (
            ScoreResponse.model_validate(response.json()).model_version == model.version
        )
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert len(events) == 2
    assert all(event["model_artifact_sha256"] == expected_sha256 for event in events)


def test_tiny_imbalanced_indices_are_finite_and_below_supported_minimum_rejected(
    request_payload, tmp_path
):
    for transaction in request_payload["transactions"]:
        if transaction["direction"] == "in":
            transaction["amount_index"] = 1e-12
    with TestClient(
        create_app(audit_path=tmp_path / "numeric-boundary.jsonl")
    ) as client:
        accepted = client.post("/score", json=request_payload)
        assert accepted.status_code == 200
        result = ScoreResponse.model_validate(accepted.json())
        assert result.capacity_score == 0
        assert result.recommended_loan.suggested_principal_index == 0
        request_payload["transactions"][0]["amount_index"] = 1e-300
        rejected = client.post("/score", json=request_payload)
        assert rejected.status_code == 422
        assert "recommended_loan" not in rejected.json()
    events = [
        json.loads(line)
        for line in (tmp_path / "numeric-boundary.jsonl").read_text().splitlines()
    ]
    assert [event["status"] for event in events if "status" in event] == [200, 422]
