"""Measured final API latency on disclosed synthetic inputs, never accuracy."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from final_model.api import create_app


def synthetic_payload() -> dict:
    transactions = []
    for offset in range(36):
        month_id = 2023 * 12 + 9 + offset
        month = month_id % 12
        prefix = f"{month_id // 12:04d}-{month + 1:02d}"
        inflow = 10_000_000 * (1 + 0.45 * math.sin(2 * math.pi * month / 12))
        for direction, amount in (("in", inflow), ("out", inflow * 0.3)):
            transactions.append(
                {
                    "ts": f"{prefix}-01T12:00:00Z",
                    "direction": direction,
                    "channel": "card" if direction == "in" else "transfer",
                    "amount_index": amount,
                }
            )
    return {
        "business_id": "disclosed-synthetic-latency-input",
        "currency": "UZS",
        "as_of_date": "2026-09-30",
        "requested_amount": None,
        "transactions": transactions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 20 <= args.requests <= 200:
        parser.error("requests must be between 20 and 200")
    payload = synthetic_payload()
    timings = []
    with tempfile.TemporaryDirectory(prefix="flowcredit-latency-") as directory:
        audit_path = Path(directory) / "audit.jsonl"
        started = time.perf_counter()
        with TestClient(create_app(audit_path=audit_path)) as client:
            startup_ms = (time.perf_counter() - started) * 1000
            health = client.get("/health").json()
            for position in range(args.requests + 1):
                started = time.perf_counter()
                response = client.post("/score", json=payload)
                elapsed = (time.perf_counter() - started) * 1000
                if response.status_code != 200:
                    raise RuntimeError(f"Real scorer failed: {response.status_code}")
                if position:
                    timings.append(elapsed)
                else:
                    first_request_ms = elapsed
            events = [json.loads(row) for row in audit_path.read_text().splitlines()]
        completed = sum(row["event"] == "assessment_completed" for row in events)
        if completed != args.requests + 1:
            raise RuntimeError("Successful requests were not durably audited")
    report = {
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "provenance": "disclosed_synthetic_input_actual_final_model",
        "scope": "In-process FastAPI HTTP serialization, real model inference, validation and durable audit; excludes network, Nest, browser, concurrency and cloud load",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "model_version": health["model_version"],
        "model_artifact_sha256": health["model_artifact_sha256"],
        "history_months": 36,
        "transaction_rows": len(payload["transactions"]),
        "warm_requests": args.requests,
        "startup_ms": startup_ms,
        "first_request_ms": first_request_ms,
        "median_ms": statistics.median(timings),
        "p95_nearest_rank_ms": sorted(timings)[math.ceil(0.95 * len(timings)) - 1],
        "min_ms": min(timings),
        "max_ms": max(timings),
        "durably_completed_requests": completed,
        "external_inference_api_calls": 0,
        "samples_ms": timings,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "model_version",
                    "median_ms",
                    "p95_nearest_rank_ms",
                    "warm_requests",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
