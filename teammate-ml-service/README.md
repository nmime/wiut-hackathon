# Frozen teammate source and research candidate

This private FastAPI service adapts the teammate's frozen LightGBM forecast and
capacity service to the existing Nest `/score` transport. The product serves the [final combined scorer](../docs/final-model-runtime.md),
which reuses verified financial primitives from this source. This historical
LightGBM bridge is retained for isolated research and regression only. This candidate has **420 synthetic training
businesses and no validated real-borrower accuracy**. Its native synthetic
evaluation is not evidence that it improves the existing real-data model.

The maintainer supplied `ml-service.zip`; its SHA-256 is
`c0a062c8b700fe0824fbcb746db4615d1fab3ad8c7360adf7133e706ea2039db`.
Selected original runtime files and native text/JSON model artifacts are copied
byte-for-byte into `vendor/`. The original numerical model is unchanged. The
archive's generator, training entry point, public demo UI, unauthenticated
assessment/audit/decision endpoints and transaction datasets are excluded from
the runtime. The synthetic CSV under `tests/` is exclusively a test fixture.

`vendor-manifest.json` records the original file sizes and SHA-256 hashes. The
artifact identity is the SHA-256 of canonical JSON mapping every artifact path
to its SHA-256, covering inflow/outflow boosters, calibration, conformal tables,
industry priors, population and metadata. Its value is
`51091e827f0b9d768878bd8e414e2c10dd18c7e3dee884acb3680b722bfa8d1a`.
Startup verifies all 25 frozen vendor files and loads an isolated snapshot of
those verified bytes. Replacing the source artifact path after startup cannot
change the loaded model or its health/audit identity. Native artifacts are text,
with no pickle deserialization or automatic retraining. The bridge's separate
source hash also appears in health, audits and the model-version suffix, so a
transport-policy change is distinguishable from a numerical artifact change.

The original teammate README is retained in `vendor/README.md` as source
material. Its instructions and claims do not configure this wrapper. See
`../docs/teammate-ml-review.md` for independent review, reproduced tests,
validation defects, data lineage and the default-model decision.

## Run privately

Use Python 3.12.13 and the committed dependency lock:

```sh
cd teammate-ml-service
uv sync --frozen
ML_AUDIT_PATH=runtime/requests.jsonl OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  uv run --frozen uvicorn teammate_bridge.api:app --host 127.0.0.1 --port 8111
```

The service exposes `/health` and `/score`. Only a separate research/test Nest instance may connect to this endpoint.
Production Compose has one final `ml` service and does not select this candidate. No candidate port should be published to the
internet. The Docker image runs as UID/GID 10001 and writes only to the durable
audit volume at `/data/audit`. It retains one inference slot and caps numerical
threading; it returns a retryable HTTP 429 while that slot is busy. There are no
external LLM calls even if `ML_ENABLE_LLM=1` is inherited.

## Transport and financial policy

- `/score` accepts the shared business ID, requested amount, UZS currency,
  assessment date and at most 20,000 transaction rows. JSON bodies are bounded
  at 5 MiB; dates, amounts, unknown fields and future transactions are validated.
  At most 50 years of history are accepted to bound monthly allocations.
- Monetary conversion is explicit: **1 amount_index = 1 UZS**. Use actual UZS
  imports. Transaction amounts are preserved as decimal representations of the
  accepted numbers, without scientific notation or arbitrary rounding.
- Original timestamp calendar components are preserved to match the existing
  contract's month grouping. The timezone offset is removed before the vendor
  interprets the timestamp as Tashkent local time. `cash_in` maps to native
  `cash`; transaction IDs are stable hashes of business ID and row position.
  The adapter adds no inferred counterparties, categories or debt labels.
- A completed calendar month-end is required. This keeps the native next 12
  forecast months aligned with the assessment and first following-month payment.
  Cutoffs outside December 2019–December 2028 are refused because the native
  Ramadan calendar covers 2018–2029 and forecast features look back two years.
  Future cutoffs are also refused. The numerical calendar is not extended with
  invented dates or unknown Ramadan values.
- Fewer than six complete history months returns HTTP 422 with an actionable
  refusal, without a fabricated score or forecast. Six to eleven months uses
  the vendor's genuine annuity fallback, with no estimated seasonal schedule.
  Twelve to twenty-three months has reduced seasonality confidence; 24 or more
  uses the native full mode. The vendor excludes a first month when its earliest
  transaction is day 10 or later and treats gaps in the accepted history as zero
  observed transactions. Review missing statement coverage before scoring.
- The native **24% annual interest and 12-month term** are retained. The response
  includes validated `loan_terms` with actual schedule type, principal, interest
  and total repayments. Aggregate displayed interest is the sum of the vendor's
  rounded payment rows minus its rounded principal; the unmodified native
  interest/principal/balance rows remain in the audit. The zero-interest flag is
  never used. A zero requested amount means no requested amount, as in the
  native implementation.
- The native request is checked against main-tier and higher-risk capacity. If
  requested terms do not fit the main tier, a second genuine native assessment
  with no requested amount supplies the main-tier recommendation and repayment
  schedule. Both complete native responses are retained in the audit, and the
  original request status and fallback are disclosed. An officer makes every
  final decision in Nest; the bridge cannot approve or decline a loan.
- Native capacity score, confidence and free-cash-flow forecast values are
  preserved. The transport's score bands use 70/40 cutoffs; trend labels use
  native annual log trend above +5% or below −5%; schedule labels compare native
  payments with native annuity payments using a 2% threshold. These are display
  mappings, not newly validated borrower outcomes. Missing incoming revenue
  needed for a finite volatility statistic returns an actionable refusal.
- The shared import has no category or counterparty columns. Fixed costs,
  existing debt, own transfers and concentration cannot be independently
  identified. No external debt is fabricated. Flags and advisory text disclose
  these limitations and the solely synthetic training provenance.

## Audit and validation

Every `/score` attempt gets a request ID, SHA-256 of the received body (bounded
prefix for oversized input), loaded model identity and source identities. The
wrapper durably appends `assessment_requested` before inference and a completion
or failure after it, using an interprocess file lock and `fsync`. Responses are
buffered until the final audit entry is durable; unavailable audit storage
returns HTTP 503 and releases no recommendation. Successful records contain the
validated transport response and complete native assessment responses. Refusals
also retain the native refusal response when inference reached that stage.

The log is private, append-only operational evidence. It is **not** externally
anchored, tamper-proof storage. Back it up and restrict access. Nest remains the
tenant and officer-decision authority and also persists every assessment attempt.

```sh
uv run ruff check teammate_bridge tests
uv run ruff format --check teammate_bridge tests
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 uv run pytest -q
```

From the repository root, `pnpm test:teammate-ml` exercises the actual candidate,
Nest, PostgreSQL and React through the separate opt-in integration configuration.
It does not select the candidate for the default application or alter any frozen
real-data validation evidence.
