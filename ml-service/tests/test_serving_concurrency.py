"""Concurrent real inference must preserve predictions and correlated audits."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from capacity_ml.api import create_app
from capacity_ml.schemas import ScoreResponse


def test_concurrent_scores_are_deterministic_and_each_audit_is_complete(
    model, request_payload, tmp_path
):
    audit_path = tmp_path / "concurrent-audit.jsonl"
    with TestClient(create_app(audit_path=audit_path)) as client:
        with Path(os.environ.get("ML_MODEL_PATH", "runtime/model.joblib")).open(
            "rb"
        ) as artifact:
            expected_artifact_sha256 = hashlib.file_digest(
                artifact, "sha256"
            ).hexdigest()
        assert client.get("/health").json()["model_artifact_sha256"] == (
            expected_artifact_sha256
        )

        def assess(position):
            request_id = f"concurrent-real-score-{position}"
            reply = client.post(
                "/score",
                json=request_payload,
                headers={"x-request-id": request_id},
            )
            assert reply.status_code == 200
            result = ScoreResponse.model_validate(reply.json())
            assert result.model_version == model.version
            assert result.request_id == reply.headers["x-request-id"] == request_id
            return result.model_dump()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(assess, range(12)))

    comparable = [
        {key: value for key, value in result.items() if key != "request_id"}
        for result in results
    ]
    assert all(result == comparable[0] for result in comparable)
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert len(events) == 24
    assert all(
        event["model_artifact_sha256"] == expected_artifact_sha256 for event in events
    )
    for result in results:
        correlated = [
            event for event in events if event["request_id"] == result["request_id"]
        ]
        assert [event["event"] for event in correlated] == [
            "assessment_requested",
            "assessment_completed",
        ]
        assert correlated[1]["result"] == result
        assert correlated[1]["model_version"] == model.version
        assert correlated[1]["input_hash"] == correlated[0]["input_hash"]
        assert correlated[1]["status"] == 200
