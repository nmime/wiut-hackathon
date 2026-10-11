#!/usr/bin/env python3
"""Measure the actual private scorer using disclosed synthetic test inputs."""

from __future__ import annotations

import argparse
import json

from common import OperationError, compose, model_health, run

PROBE = r"""
import datetime, hashlib, json, math, os, pathlib, statistics, time, urllib.request
from teammate_bridge.schemas import ScoreResponse
count = REQUEST_COUNT
last = datetime.date.today().replace(day=1) - datetime.timedelta(days=1)
last_month = last.year * 12 + last.month - 1
transactions = []
for offset, month_id in enumerate(range(last_month - 35, last_month + 1)):
    prefix = f'{month_id // 12:04d}-{month_id % 12 + 1:02d}'
    revenue = 1000000 * (1 + .15 * math.sin(offset * math.pi / 6))
    transactions.extend([
        {'ts': prefix + '-05T12:00:00Z', 'direction': 'in', 'channel': 'card', 'amount_index': revenue},
        {'ts': prefix + '-06T12:00:00Z', 'direction': 'out', 'channel': 'transfer', 'amount_index': 450000.0},
    ])
payload = {'business_id':'test-only-submission-latency','as_of_date':last.isoformat(),'currency':'UZS','requested_amount':None,'transactions':transactions}
body = json.dumps(payload, sort_keys=True, separators=(',',':'), allow_nan=False).encode()
audit = pathlib.Path(os.environ['ML_AUDIT_PATH'])
audit_offset = audit.stat().st_size if audit.exists() else 0
samples, versions, response_hashes = [], set(), {}
for index in range(count + 3):
    request = urllib.request.Request('http://127.0.0.1:8000/score', data=body, headers={'Content-Type':'application/json'})
    start = time.perf_counter_ns()
    with urllib.request.urlopen(request, timeout=30) as response:
        result = ScoreResponse.model_validate_json(response.read())
        assert response.status == 200
    elapsed = (time.perf_counter_ns() - start) / 1000000
    assert result.loan_terms.annual_rate == .24
    assert 'final_combined_model' in result.flags
    versions.add(result.model_version)
    response_hashes[result.request_id] = hashlib.sha256(json.dumps(result.model_dump(mode='json'), sort_keys=True, separators=(',',':'), allow_nan=False).encode()).hexdigest()
    if index >= 3:
        samples.append(elapsed)
assert len(versions) == 1
with audit.open('rb') as records:
    records.seek(audit_offset)
    matched = [json.loads(line) for line in records if line.strip()]
matched = [row for row in matched if row.get('request_id') in response_hashes]
requested = [row for row in matched if row.get('event') == 'assessment_requested']
completed = [row for row in matched if row.get('event') == 'assessment_completed']
assert len(requested) == len(completed) == count + 3
assert all(row['response_hash'] == response_hashes[row['request_id']] for row in completed)
ordered = sorted(samples)
print(json.dumps({'input_scope':'disclosed_synthetic_runtime_test_only','real_accuracy_claim':False,'measurement_scope':'warmed loopback HTTP including validated response and durable ML audit','warmup_requests':3,'measured_requests':count,'verified_audit_requests':len(requested),'verified_audit_completions':len(completed),'audit_response_hashes_match':True,'history_months':36,'transaction_rows':72,'as_of_date':last.isoformat(),'input_sha256':hashlib.sha256(body).hexdigest(),'model_version':next(iter(versions)),'latency_ms':{'median':statistics.median(samples),'p95':ordered[math.ceil(.95*count)-1],'min':min(samples),'max':max(samples),'samples':samples}},allow_nan=False))
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=20, choices=range(5, 101))
    options = parser.parse_args()
    try:
        identity = model_health("ml")
        result = json.loads(
            run(
                compose(
                    "exec",
                    "-T",
                    "ml",
                    "python",
                    "-c",
                    PROBE.replace("REQUEST_COUNT", str(options.requests)),
                ),
                timeout=options.requests * 30 + 120,
            )
        )
        if result.get("model_version") != identity["model_version"]:
            raise OperationError("Scorer identity changed during timing")
        print(
            json.dumps(
                {**result, "verified_model_identity": identity},
                sort_keys=True,
                allow_nan=False,
            )
        )
        return 0
    except (OperationError, OSError, ValueError):
        print("Scorer timing failed; no latency result was published.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
