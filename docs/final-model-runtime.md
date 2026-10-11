# Final local FlowCredit scorer

The product serves one assembled model through `final_model.api:app`. Its revenue
forecast uses the candidate selected by the fresh real-data experiment; the frozen
incumbent is retained whenever a replacement fails the predefined accuracy gates.
Historical model endpoints remain available for explicit regression and research.

The assembly combines real-revenue forecasting and uncertainty calibration,
observed borrower expense projection, and the teammate's verified financial
primitives. It applies **24% annual interest** over **12 months**. Affordability is
computed for the seasonal schedule actually offered. The same-principal annuity
is a comparator, rather than the rule used to size that seasonal offer.

Three advisory verdict flags are returned: `verdict_affordable`,
`verdict_elevated_risk`, and `verdict_decline`. An elevated-risk offer needs an
officer's judgment. A sustained-decline guard suppresses positive recommendations;
a wide band alone does not automatically refuse a seasonal business whose median
supports an offer. These rules express payment capacity, not default probability.
An officer records every final decision.

The shared `/score` contract is preserved, including existing `loan_terms` and
`forecast_provenance`. The frontend shows the advisory verdict, actual interest,
principal, total repayment, and seasonal payments. Original stored assessments
continue to render through the same schemas.

## Run locally

From the repository root:

```sh
uv sync --frozen --directory hybrid-runtime
./scripts/serve_final_model.sh
```

Set `ML_SERVICE_URL=http://127.0.0.1:8110` for NestJS. The script accepts
`FINAL_MODEL_HOST`, `FINAL_MODEL_PORT`, `FINAL_MODEL_BUNDLE`, and `ML_AUDIT_PATH`.
Its defaults are loopback port 8110, the committed final bundle, and
`hybrid-runtime/runtime/final-audit.jsonl`. Run one Uvicorn worker because the
default audit writer coordinates threads in one process.

The combined dependencies are pinned in `hybrid-runtime/uv.lock`. This separate
environment preserves the original `ml-service/uv.lock`, training recipe, and
historical benchmark identities. Both source roots are placed on `PYTHONPATH`;
no inference service, data provider, or language model is called externally.

The optional local container stack uses the final scorer:

```sh
docker compose -f docker-compose.yml -f docker-compose.ml.yml up --build
```

Both this stack and production Compose build `hybrid-runtime/Dockerfile` from the
repository root. Builds copy accepted artifacts and never retrain a model. The
original `ml-service/Dockerfile` and teammate bridge remain opt-in research tools.
Changing Compose does not deploy or migrate an existing installation.

## Frozen components and audit

The exact previously measured incumbent artifact is committed at
`ml-service/final_model/artifacts/baseline.joblib`. Its SHA-256 is
`31693530f17dbd481752d0996b0d4131c65ee0af859346a8f83aea7f17283b96`.
It is a trusted project artifact, rather than a retrained substitute. Startup
verifies its identity and the final bundle. Unchanged teammate source/artifacts
are checked against `teammate-ml-service/vendor-manifest.json` and loaded from an
isolated snapshot. A missing, corrupt or mismatched component fails startup;
no recommendation fallback is fabricated.

`GET /health` reports `model_version`, a SHA-256 of the complete assembly identity,
and constituent revenue, calibration, vendor, source and dependency identities.
Here `model_artifact_sha256` identifies the assembled deployment, not one joblib
file; `identity_scope` declares this explicitly. The identity remains fixed for
the loaded process until restart. The original scorer retains its original
serialized-artifact identity.

Every direct `/score` attempt records a request hash and durable success or failure
before releasing a response. Successful events retain the validated response,
component identities, calibrated forecasts, projected expenses, tier capacities,
amortization, and same-principal annuity comparator. Input transaction rows are
not duplicated into ML audit entries. Audit failure returns 503 and releases no
recommendation. NestJS separately validates and persists the assessment and
officer decision within its tenant.

The financial audit must remain private. The existing backup volume path is
retained. After a deliberate deployment, an operator must explicitly accept the
new healthy identity before operations monitoring uses it as the baseline.

## Validation and limits

The [fresh real-revenue analysis](../ml-service/reports/revenue-upgrade-fresh.md)
and [machine evidence](../ml-service/reports/revenue-upgrade-fresh.json)
records the frozen development selection, untouched source holdout, actual
interval coverage and promotion gates. The
incumbent is retained: new blend gains of 2.181% on the primary panel and 1.338%
on the latest year fail the frozen 5% gates. The nominal 80% central revenue band
covers 70.724% of fresh Canadian observations and 87.037% of NZ observations;
these empirical limits remain disclosed. The
[financial behaviour report](../ml-service/reports/final-financial-behavior.md)
records the separate disclosed synthetic schedule comparisons, including a case
where the seasonal offer performs worse than an annuity after an unexpected
change. Neither report is a real borrower repayment validation.

```sh
uv run --frozen --directory hybrid-runtime pytest
docker compose exec -T db createdb -U wiut wiut_final_ml
pnpm test:final-ml
```

The final browser suite uses disclosed synthetic borrower fixtures in the
separate `wiut_final_ml` database and ports 8112/3012/5178.
`WIUT_FINAL_ML_DATABASE_URL` can override its connection. Existing
`pnpm test:real-ml` and `pnpm test:teammate-ml` suites retain the historical
endpoints, environments and separate databases.

Real public revenue supports forecast and interval evaluation. It supplies no
borrower expense, net-flow, repayment or default labels. Expenses are projected
from the scored business's observed transactions; future expense coverage is
unverified. Comparisons with synthetic future costs are disclosed behaviour
checks. Aggregate interval transfer to an individual borrower remains a
limitation, and interval coverage is not repayment probability.

Actual UZS imports have an explicit conversion: **1 amount index = 1 UZS**.
Historical index-only assessments retain their original unit. This runtime never
seeds business accounts, assessments or decisions with synthetic demo data.
