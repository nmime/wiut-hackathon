"""Model outputs are always computed; fabricated observations are test-only."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from teammate_bridge.api import MAX_BODY_BYTES, create_app, transaction_csv
from teammate_bridge.audit import DurableAudit
from teammate_bridge.loader import ROOT, load_candidate
from teammate_bridge.schemas import ScoreRequest, ScoreResponse

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"


@pytest.fixture
def payload():
    # Original teammate synthetic holdout input, not a production demo customer.
    original = csv.DictReader(
        (Path(__file__).parent / "stable-synthetic-fixture.csv")
        .read_text()
        .splitlines()
    )
    transactions = [
        {
            "ts": row["timestamp"],
            "direction": row["direction"],
            "channel": "cash_in" if row["channel"] == "cash" else row["channel"],
            "amount_index": float(row["amount"]),
        }
        for row in original
    ]
    return {
        "business_id": "test-only-teammate-bridge",
        "as_of_date": "2025-09-30",
        "currency": "UZS",
        "requested_amount": None,
        "transactions": transactions,
    }


@pytest.fixture
def audit_path(tmp_path):
    return tmp_path / "requests.jsonl"


@pytest.fixture
def client(audit_path):
    with TestClient(create_app(audit_path)) as client:
        yield client


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def trim_history(payload, count):
    result = copy.deepcopy(payload)
    months = sorted({row["ts"][:7] for row in result["transactions"]})[-count:]
    result["transactions"] = [
        row for row in result["transactions"] if row["ts"][:7] in months
    ]
    return result


def test_startup_identity_and_no_vendor_public_routes(client):
    health = client.get("/health").json()
    assert (
        health["model_artifact_sha256"]
        == "51091e827f0b9d768878bd8e414e2c10dd18c7e3dee884acb3680b722bfa8d1a"
    )
    assert (
        health["model_version"]
        == f"teammate-v1-m-f7d2fc389743-51091e827f0b-{health['bridge_source_sha256'][:8]}"
    )
    assert health["training_businesses"] == 420
    assert health["synthetic_training_only"] is True
    assert health["external_llm_enabled"] is False
    for route in [
        "/v1/assess",
        "/v1/audit/verify",
        "/v1/assessments/any",
        "/",
        "/v1/schema",
    ]:
        assert client.get(route).status_code == 404
    assert (
        client.post(
            "/v1/assessments/any/decision", json={"decision": "approved"}
        ).status_code
        == 404
    )


def test_score_maps_actual_vendor_outputs_and_reconciles_interest(
    client, payload, audit_path
):
    response = client.post(
        "/score", json=payload, headers={"x-request-id": "bridge-contract-test"}
    )
    assert response.status_code == 200, response.text
    result = ScoreResponse.model_validate(response.json())
    audit = records(audit_path)
    assert [row["event"] for row in audit] == [
        "assessment_requested",
        "assessment_completed",
    ]
    raw = audit[-1]["vendor_assessments"][0]["payload"]
    assert result.capacity_score == raw["capacity"]["capacity_score"]
    assert result.confidence == raw["capacity"]["confidence"]["value"]
    assert result.seasonality.monthly_forecast_index == [
        row["free_cash_flow_p50"] for row in raw["forecast"]
    ]
    assert result.loan_terms.annual_rate == 0.24
    assert result.loan_terms.total_interest_index > 0
    assert result.loan_terms.total_repayment_index == pytest.approx(
        sum(row.installment_index for row in result.adaptive_schedule)
    )
    assert result.loan_terms.total_repayment_index == pytest.approx(
        result.recommended_loan.suggested_principal_index
        + result.loan_terms.total_interest_index
    )
    assert "zero_interest_mvp" not in result.flags
    assert {
        "category_unavailable",
        "counterparty_unavailable",
        "synthetic_training_only",
        "amount_index_1_to_1_uzs",
    } <= set(result.flags)
    assert (
        result.request_id == response.headers["x-request-id"] == "bridge-contract-test"
    )
    assert audit[-1]["result"] == response.json()
    assert (
        audit[-1]["model_artifact_sha256"]
        == client.get("/health").json()["model_artifact_sha256"]
    )
    assert (
        raw["audit"]["csv_sha256"]
        == hashlib.sha256(
            transaction_csv(ScoreRequest.model_validate(payload))
        ).hexdigest()
    )
    assert set(raw["forecast"][0]) >= {"inflow_p10", "inflow_p50", "inflow_p90"}
    assert raw["data_quality"]["warnings"]


def test_excess_requested_amount_returns_genuine_main_tier_recommendation(
    client, payload, audit_path
):
    payload["requested_amount"] = 1e14
    response = client.post("/score", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    calls = records(audit_path)[-1]["vendor_assessments"]
    assert len(calls) == 2
    assert calls[0]["payload"]["schedule"]["status"] in {
        "exceeds_capacity",
        "within_risk_capacity",
        "no_capacity",
    }
    assert calls[0]["payload"]["audit"]["params"]["requested_amount"] == 1e14
    assert calls[1]["payload"]["audit"]["params"]["requested_amount"] is None
    assert (
        result["recommended_loan"]["suggested_principal_index"]
        == calls[1]["payload"]["schedule"]["amount"]
    )
    assert result["recommended_loan"]["suggested_principal_index"] < 1e14
    assert "requested_amount_exceeds_main_capacity" in result["flags"]
    assert result["loan_terms"]["requested_amount_policy"] == "capacity_checked"


def test_six_to_eleven_months_return_native_annuity_fallback(client, payload):
    response = client.post("/score", json=trim_history(payload, 8))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["loan_terms"]["schedule_type"] == "annuity"
    assert "adaptive_schedule_unavailable_annuity_used" in result["flags"]
    assert len(result["adaptive_schedule"]) == 12
    assert len({row["installment_index"] for row in result["adaptive_schedule"]}) == 1


def test_insufficient_history_is_audited_refusal_without_fabricated_result(
    client, payload, audit_path
):
    response = client.post("/score", json=trim_history(payload, 3))
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "insufficient_history"
    assert "capacity_score" not in response.json()
    audit = records(audit_path)
    assert audit[-1]["event"] == "assessment_failed"
    assert audit[-1]["status"] == 422
    assert audit[-1]["vendor_assessments"][0]["payload"]["status"] == "refused"
    assert audit[-1]["vendor_assessments"][0]["payload"]["capacity"] is None
    assert "result" not in audit[-1]


def test_midmonth_is_actionable_refusal_and_does_not_call_vendor(
    client, payload, audit_path
):
    payload["as_of_date"] = "2025-10-15"
    response = client.post("/score", json=payload)
    assert response.status_code == 422
    assert response.json()["code"] == "month_end_required"
    assert "completed calendar month-end" in response.json()["detail"]
    audit = records(audit_path)
    assert audit[-1]["response_problem"] == response.json()
    assert "vendor_assessments" not in audit[-1]


def test_missing_ramadan_calendar_is_refused_instead_of_zero_filled(
    client, payload, audit_path
):
    payload["transactions"] = [
        {
            **row,
            "ts": row["ts"]
            .replace("2023", "2015")
            .replace("2024", "2016")
            .replace("2025", "2017"),
        }
        for row in payload["transactions"]
    ]
    payload["as_of_date"] = "2017-09-30"
    response = client.post("/score", json=payload)
    assert response.status_code == 422
    assert response.json()["code"] == "unsupported_calendar"
    assert "vendor_assessments" not in records(audit_path)[-1]


@pytest.mark.parametrize(
    "mutation",
    [
        "bad_date",
        "future_cutoff",
        "after_cutoff",
        "currency",
        "nan",
        "negative",
        "unknown_column",
        "row_limit",
    ],
)
def test_invalid_inputs_are_bounded_and_audited(client, payload, audit_path, mutation):
    if mutation == "bad_date":
        payload["as_of_date"] = "2025-99-99"
    elif mutation == "future_cutoff":
        payload["as_of_date"] = "9999-12-31"
    elif mutation == "after_cutoff":
        payload["transactions"][0]["ts"] = "2025-10-01T10:00:00Z"
    elif mutation == "currency":
        payload["currency"] = "USD"
    elif mutation == "nan":
        payload["transactions"][0]["amount_index"] = "NaN"
    elif mutation == "negative":
        payload["transactions"][0]["amount_index"] = -1
    elif mutation == "unknown_column":
        payload["transactions"][0]["category"] = "transfer_own"
    else:
        payload["transactions"] = [payload["transactions"][0]] * 20001
    response = client.post("/score", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_input"
    assert len(response.content) < 16384
    assert records(audit_path)[-1]["status"] == 422
    assert "result" not in records(audit_path)[-1]


def test_payload_limit_audits_prefix_and_never_scores(client, audit_path):
    response = client.post(
        "/score",
        content=b"x" * (MAX_BODY_BYTES + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    last = records(audit_path)[-1]
    assert last["input_hash_scope"] == "prefix"
    assert last["input_hash"] == hashlib.sha256(b"x" * MAX_BODY_BYTES).hexdigest()
    assert "vendor_assessments" not in last


def test_busy_scorer_returns_retryable_audited_failure(client, payload, audit_path):
    slot = client.app.state.inference_slot
    slot.acquire()
    try:
        response = client.post("/score", json=payload)
    finally:
        slot.release()
    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"
    assert records(audit_path)[-1]["status"] == 429


def test_audit_failure_prevents_releasing_a_recommendation(
    client, payload, monkeypatch
):
    def fail(_record):
        raise OSError("Test-only unavailable storage")

    monkeypatch.setattr(client.app.state.audit, "append", fail)
    response = client.post("/score", json=payload)
    assert response.status_code == 503
    assert "recommendation" in response.json()["detail"]
    assert "capacity_score" not in response.json()


def test_timezone_components_amounts_and_generated_ids_are_preserved(payload):
    payload["transactions"][0]["ts"] = "2023-04-30T23:30:00-03:00"
    payload["transactions"][0]["amount_index"] = 1.2345678901234567
    payload["transactions"][1]["amount_index"] = 1e-12
    request = ScoreRequest.model_validate(payload)
    rows = list(csv.DictReader(io.StringIO(transaction_csv(request).decode())))
    assert rows[0]["timestamp"] == "2023-04-30T23:30:00"
    assert float(rows[0]["amount"]) == request.transactions[0].amount_index
    assert float(rows[1]["amount"]) == request.transactions[1].amount_index
    assert {row["currency"] for row in rows} == {"UZS"}
    assert "category" not in rows[0] and "counterparty_id" not in rows[0]
    assert len({row["txn_id"] for row in rows}) == len(rows)
    assert transaction_csv(request) == transaction_csv(request)


def test_concurrent_durable_append_keeps_complete_separate_json_records(tmp_path):
    audit = DurableAudit(tmp_path / "concurrent.jsonl")
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(
            workers.map(
                lambda index: audit.append(
                    {"event": "test_only", "id": index, "payload": "x" * 4096}
                ),
                range(64),
            )
        )
    logged = records(audit.path)
    assert len(logged) == 64
    assert {row["id"] for row in logged} == set(range(64))
    assert all(row["payload"] == "x" * 4096 for row in logged)


def test_actual_fsync_failure_does_not_release_score(client, payload, monkeypatch):
    def unavailable_storage(_descriptor):
        raise OSError("Test-only fsync failure")

    monkeypatch.setattr("teammate_bridge.audit.os.fsync", unavailable_storage)
    response = client.post("/score", json=payload)
    assert response.status_code == 503
    assert "capacity_score" not in response.json()


def test_changed_model_metadata_or_source_fails_startup(tmp_path):
    vendor = tmp_path / "vendor"
    shutil.copytree(ROOT / "vendor", vendor)
    metadata = vendor / "models/artifacts/meta.json"
    metadata.write_text(
        metadata.read_text().replace("m-f7d2fc389743", "forged-version")
    )
    with pytest.raises(RuntimeError, match="Frozen teammate artifact/source changed"):
        load_candidate(vendor)
    shutil.copyfile(ROOT / "vendor/models/artifacts/meta.json", metadata)
    (vendor / "models/capacity.py").write_text(
        "raise RuntimeError('test-only forged source')"
    )
    with pytest.raises(RuntimeError, match="Frozen teammate artifact/source changed"):
        load_candidate(vendor)


def test_loaded_identity_survives_source_path_replacement(tmp_path, payload):
    vendor = tmp_path / "vendor"
    shutil.copytree(ROOT / "vendor", vendor)
    with TestClient(create_app(tmp_path / "audit.jsonl", vendor)) as client:
        health = client.get("/health").json()
        (vendor / "models/artifacts/lgb_inflow.txt").write_bytes(
            b"test-only replaced artifact"
        )
        (vendor / "models/capacity.py").write_text(
            "raise RuntimeError('test-only replaced source')"
        )
        response = client.post("/score", json=payload)
        assert response.status_code == 200, response.text
        assert client.get("/health").json() == health
        assert (
            records(tmp_path / "audit.jsonl")[-1]["model_artifact_sha256"]
            == health["model_artifact_sha256"]
        )


def test_llm_environment_cannot_enable_network_calls(tmp_path, payload, monkeypatch):
    monkeypatch.setenv("ML_ENABLE_LLM", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-never-used")
    import httpx

    def no_network(*_args, **_kwargs):
        raise AssertionError("External LLM request must never be attempted")

    monkeypatch.setattr(httpx, "post", no_network)
    with TestClient(create_app(tmp_path / "audit.jsonl")) as client:
        response = client.post("/score", json=payload)
        assert response.status_code == 200, response.text
        assert client.get("/health").json()["external_llm_enabled"] is False
        assert (
            records(tmp_path / "audit.jsonl")[-1]["vendor_assessments"][0]["payload"][
                "explanations"
            ]["advice_llm"]
            is None
        )
