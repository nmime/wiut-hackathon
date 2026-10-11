"""Smoke-test the production image offline with explicit synthetic input."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from teammate_bridge.schemas import ScoreResponse


def main():
    with tempfile.TemporaryDirectory(prefix="flowcredit-image-smoke-") as directory:
        audit = Path(directory) / "audit.jsonl"
        environment = {**os.environ, "ML_AUDIT_PATH": str(audit)}
        service = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "final_model.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--workers",
                "1",
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            health = None
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if service.poll() is not None:
                    raise RuntimeError(
                        "Image startup failed: " + service.stderr.read().decode()
                    )
                try:
                    with urlopen("http://127.0.0.1:8000/health", timeout=1) as response:
                        health = json.load(response)
                    break
                except (URLError, TimeoutError):
                    time.sleep(0.2)
            if health is None:
                raise RuntimeError("Image scorer did not become healthy")
            assert health["serving_mode"] == "final_combined_model"
            assert health["local_inference"] is True
            assert health["annual_interest_rate"] == 0.24
            assert health["component_identity"]["revenue"]["baseline_sha256"] == (
                "31693530f17dbd481752d0996b0d4131c65ee0af859346a8f83aea7f17283b96"
            )
            transactions = []
            for offset in range(24):
                year, month = 2024 + offset // 12, offset % 12 + 1
                for direction, amount in (("in", 1_000_000.0), ("out", 300_000.0)):
                    transactions.append(
                        {
                            "ts": f"{year:04d}-{month:02d}-01T12:00:00Z",
                            "direction": direction,
                            "channel": "card" if direction == "in" else "transfer",
                            "amount_index": amount,
                        }
                    )
            payload = {
                "business_id": "synthetic-offline-image-smoke",
                "as_of_date": "2025-12-31",
                "currency": "UZS",
                "requested_amount": None,
                "transactions": transactions,
            }
            request = Request(
                "http://127.0.0.1:8000/score",
                data=json.dumps(payload).encode(),
                headers={
                    "content-type": "application/json",
                    "x-request-id": "synthetic-image-smoke",
                },
                method="POST",
            )
            with urlopen(request, timeout=15) as response:
                result = ScoreResponse.model_validate(json.load(response))
            assert result.model_version == health["model_version"]
            assert result.loan_terms.annual_rate == 0.24
            assert result.loan_terms.total_interest_index > 0
            assert result.recommended_loan.suggested_principal_index > 0
            malformed = Request(
                "http://127.0.0.1:8000/score",
                data=json.dumps({**payload, "extra": True}).encode(),
                headers={"content-type": "application/json"},
                method="POST",
            )
            try:
                urlopen(malformed, timeout=15).close()
                raise AssertionError("Unknown transport field was accepted")
            except HTTPError as error:
                assert error.code == 422
            entries = [json.loads(line) for line in audit.read_text().splitlines()]
            assert [entry["event"] for entry in entries] == [
                "assessment_requested",
                "assessment_completed",
                "assessment_requested",
                "assessment_failed",
            ]
            assert entries[1]["result"] == result.model_dump(mode="json")
            assert entries[1]["financial_evidence"]["assessment"]["offered"][
                "actual_within_capacity"
            ]
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "input_scope": "synthetic_test_only",
                        "network_scope": "loopback_only",
                        "model_version": result.model_version,
                        "assembly_sha256": health["model_artifact_sha256"],
                        "annual_rate": result.loan_terms.annual_rate,
                        "audited_events": len(entries),
                    },
                    sort_keys=True,
                )
            )
        finally:
            service.terminate()
            try:
                service.wait(timeout=10)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait(timeout=5)


if __name__ == "__main__":
    main()
