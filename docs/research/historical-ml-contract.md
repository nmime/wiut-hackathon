# Archived historical ML contract notes

These notes preserve the pre-final scorer policies and their measured evidence.
They are research documentation, not the production configuration. The current
contract is [ML integration](../ml-integration.md).

# ML integration contract

The React application calls NestJS. Only NestJS communicates with the Python
service. Set `ML_SERVICE_URL` to the service base URL; the adapter appends `/score`.
`ML_TIMEOUT_MS` defaults to 8000. Scoring, forecasting, and model inference must
operate locally within the bank perimeter in a production implementation.

The product's [final local scorer](../final-model-runtime.md) implements this contract
through `final_model.api:app` in the pinned `hybrid-runtime` environment. Run the
complete stack with the `docker-compose.ml.yml` override or start
`scripts/serve_final_model.sh`. Its loan policy uses 24% annual interest, actual
seasonal schedule capacity, real-revenue intervals and three advisory verdicts.
Frontend/backend development still works with ML disconnected. Historical
`capacity_ml` and teammate bridge endpoints remain explicit research options.

## Request

```json
{
  "business_id": "business-id",
  "requested_amount": null,
  "currency": "UZS",
  "as_of_date": "2026-10-10",
  "transactions": [
    {
      "ts": "2026-10-01T12:00:00Z",
      "direction": "in",
      "channel": "qr",
      "amount_index": 20
    }
  ]
}
```

`requested_amount` is optional, nullable, nonnegative, and is in UZS as specified
in the supplied brief. The ML transport retains standardized `amount_index` fields. For user-provided
UZS imports, NestJS explicitly maps one UZS to one internal unit, and snapshots
`amount_unit` on the business and assessment. Historical synthetic records retain
index units. The final scorer declares 1 amount index = 1 UZS for actual UZS
imports and capacity-checks the requested principal against its offered schedule.
Its `loan_terms.requested_amount_policy` is `capacity_checked`. The historical
0% scorer has no such conversion and treats a requested amount as context only.
The default analysis omits the requested amount by sending `null`.

Allowed channels: `card`, `transfer`, `qr`, `cash_in`, `other`. Transaction amounts
must be finite and within **1e-12–1e12**, inclusive. Histories contain 1–20,000 transactions. Timestamps support
ISO timestamps with `Z`, timezone offset, or no offset (interpreted as UTC).
NestJS selects transactions on or before the assessment date. An empty selected
history is rejected. The business and date in the result must match the request.

## Historical local scorer limits

The following section documents the frozen `capacity_ml.api` endpoint. The final
assembled model's current policy and operational limits are documented in
[final model runtime](../final-model-runtime.md).

The teammate's transport contract remains the source of truth. The optional
implementation in `ml-service` supports a narrower calendar window: at most
240 inclusive calendar months from the earliest transaction month through the
assessment month, and assessment years 0001–9998. The 12 forecast months must
fit within the supported calendar. These implementation limits do not tighten
the general NestJS/shared transport contract. Unsupported inputs return HTTP
422 from the optional service; NestJS records the failed assessment and returns
an upstream error.

The shared transport contract and optional Python implementation both support
transaction indices **1e-12–1e12**. Smaller positive values are rejected,
avoiding overflow from dividing ordinary costs by a subnormal revenue scale.
Uniform rescaling within the supported range preserves the score.

The optional service counts missing complete months as zero activity. It omits
an incomplete assessment month from forecast features. If the only available
history is that partial month, it retains the observed events as a cold-start
fallback, reports low heuristic confidence, and recommends no positive loan.
Forecast month 1 still begins after the assessment month. Confidence is an
evidence heuristic and has not been calibrated as a probability.

Its demonstration repayment policy uses an explicit 0% interest rate, stated
in the returned rationale. Positive indexed payments sum to the indexed
principal and stay below the model's buffered forecast capacity for each
month. This forecast constraint cannot guarantee affordability against future
realized cash flow. A provided UZS request is flagged and does not constrain
the indexed principal while the conversion is undeclared.

## Response

The source of truth is `ScoreResponseSchema` in
`libs/common/api-contracts/src/index.ts`.

| Field                                      | Meaning                                                                                           |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| `capacity_score`                           | Number 0–100, payment capacity, not default probability                                           |
| `score_band`                               | `low`, `medium`, or `high`                                                                        |
| `cashflow_summary`                         | Mean inflow index, volatility, net surplus index, trend                                           |
| `recommended_loan`                         | Nonnegative indexed principal/installment, term 1–120 months, rationale                           |
| `seasonality.monthly_forecast_index`       | Exactly 12 future monthly net-flow indices, may be negative                                       |
| `seasonality.weak_months`, `strong_months` | Calendar month numbers 1–12; unique and disjoint                                                  |
| `adaptive_schedule`                        | One-based contiguous month offsets, indexed installments, notes                                   |
| `explanation.top_factors`                  | Factor names, positive/negative impact, finite weights                                            |
| `explanation.advisory`                     | Advice strings                                                                                    |
| `confidence`                               | Fraction 0–1, displayed as a percentage                                                           |
| `forecast_provenance`                      | Optional actual public/synthetic forecast weights, expense policy and real-training target count  |
| `loan_terms`                               | Optional actual annual rate, schedule type, interest, total repayment and requested-amount policy |
| `flags`                                    | Known failure and uncertainty warning strings                                                     |
| `model_version`, `request_id`              | Nonempty audit identifiers                                                                        |

The 12 forecast values correspond to the next 12 calendar months after the
assessment month. A positive principal requires a schedule matching the
suggested term. Zero-capacity recommendations may have an empty schedule.
Weak months should receive reduced payments; stronger months may receive increased
payments, within the model's affordable capacity constraints.

The optional local service returns `forecast_provenance` with
`real_revenue_weight` and `synthetic_net_weight` in 0–1 summing to one,
`expense_mode` (`observed_cost_regression`, `observed_cost_projection`,
`synthetic_trained`, or `not_used`),
`revenue_candidate`, and `real_training_targets`. These are the weights actually
used for this request, rather than a claim about forecast accuracy. The target
count includes overlapping rolling windows, not independent businesses or
repayment outcomes. Public-trained revenue ensembles also use the business's
observed history and statistical baselines. The field may be omitted or null by
the teammate's service and older stored assessments; both remain supported.

For the optional local service, `model_version` identifies the recipe and selected
policy. The `model_artifact_sha256` exposed by its `/health` endpoint and every
ML audit event identifies the exact serialized bytes loaded at startup. It stays
fixed until restart, including if the file on disk is replaced. This exact-byte
identity is separate from the shared response contract and need not be returned
by a replacement teammate service. Same-recipe builds can have different artifact
hashes and learned fingerprints across platforms.

The current local artifact uses a **65% real-revenue/observed-cost component**
and **35% synthetic net component** for sufficiently long histories. Its real
share falls to **25%** with fewer than 12 observed calendar months, or when the
positive prior-three-month inflow mean gives a recent-three/prior-three mean
ratio outside **[0.65, 1.55]**. The real revenue ensemble selects experts using
observed history only, with no future or cohort labels. A latest complete year without inflow or outflow yields
zero forecasts without trained inference and omits estimator provenance. The
selected expense projection scales predicted revenue by the median observed
outflow/inflow ratio over the latest 12 calendar months with positive inflow;
an all-zero-inflow window uses mean observed outflow. Fixed costs are included
implicitly, so projected costs may be overstated as revenue rises. This is
an observed-cost assumption; public revenue data provides no expense labels.

The original development grid measured **38 fixed and observed-history policies**,
every qualified real-revenue candidate, and two expense options. Its first
60%/25% guarded choice failed the reserved engineering audit's majority-real
requirement; the failed report remains preserved. Final policy selection uses
the original validation measurements, keeps the externally audited real candidate
and recipe unchanged, and compares 24 bounded observed-cost projections plus
the synthetic expense benchmark against those 38 transfer policies. The subsequent
fixed50 policy and subsequent median-share12 guard75/25/25 policy failed separately
reserved cohort guards; all three failed reports are preserved. This fourth
exploratory cycle selects only on original development data. It requires mean real
contribution of at least 55% and a tighter **10% development cohort buffer**, while
retaining every original error guard. Accurate `math.fsum` aggregation preserves a
mathematical 55% contribution without rounding subthreshold shares upward.
Development mean is **55%** (45 histories at 65%, 15 at 25%);
actual request shares remain reported individually. No consumed final-audit target
labels or cohort errors select the projection or policy. The separately reserved
V5 engineering cohort at positions **4,000,000–4,000,899** passed every unchanged
threshold, including the original **15% final cohort guard**.
Observed net-history routing was also considered: two 7,296-combination grids
requiring historical skill at up to three origins found no majority-qualified
policy. A 29,184-combination latest-origin variant did qualify some policies, but
adds inference and lacks supported local evidence for 31 of 60 development
histories; it was rejected for complexity and slightly worse pooled error than
the simpler selected policy. These are development experiments, not fresh audits.
The first Mac V5 audit measured **5.478% lower macro normalized net MAE** than the unchanged
synthetic reference (whole-business bootstrap 95% interval **4.408%–6.597%**),
and raw MAE **89.147625 versus 95.181494** (about 6.34% lower). Mean actual real
contribution was **53.1778%**, with 634 of 900 requests using majority-real
forecasts. All responses validated: 757 positive-principal and 143 zero-principal
recommendations. Pattern-break error still worsened **10.994%**; cold-start and
volatile-growth errors worsened 0.0843% and 0.1477%, within the unchanged cohort
tolerance. This fourth cycle follows three aggregate audit rejections. Its
interval describes case-sampling uncertainty conditional on the chosen policy
and fixed synthetic generator; it excludes sequential search and real-client
transfer uncertainty. The [accepted V5 result](../../ml-service/reports/engineering-audit-v5-frozen.md) is preserved and now consumed. The original external-provider result measured
**19.304% lower macro normalized revenue MAE** than seasonal naive. Current
consumed regression reports distinguish exact local reproduction from portable
qualification; neither supplies a new independent holdout.

Portable Linux qualification requires the same core source, policy and frozen
training recipes, and reproduces every original V5 target point within absolute
tolerance **1e-9**. The [target replay](../../ml-service/reports/engineering-audit-v5-targets.json)
was created after the first audit from its consumed cases, not new targets. A
differently fitted portable artifact must independently pass all five unchanged
acceptance gates (macro, raw and cohort errors, mean real share, real-trained
estimator use) and the original scoring invariants. The
[current engineering report](../../ml-service/reports/engineering-metrics.md) and
[JSON](../../ml-service/reports/engineering-metrics.json) retain actual metric deltas
from the frozen Mac result. Different learned fingerprints do not pass exact-fitted reproduction, even when
portable qualification passes. Strict metric equality and actual deltas are
reported separately. Portable qualification is consumed same-recipe regression,
not exact reproduction or fresh validation.
Exact-fitted local reruns remain subject to strict metric equality. The first Mac
V5 result and all four sequential cycles remain disclosed.

Actual-policy validation metrics are recorded separately from supporting
fixed-weight comparisons. Contributions describe forecast composition,
not accuracy or repayment probability. See [training and audit details](../../ml-service/README.md)
for the complete finite grid, validation guards and transfer limitations. A
replacement teammate service may use its own validated policy while preserving
the response contract.

## Error and audit behavior

The optional teammate bridge in `teammate-ml-service/` retains native 24% annual
interest and genuine annuity/adaptive payments. Its `loan_terms` declare
`annual_rate`, `schedule_type`, `total_interest_index`, `total_repayment_index`
and `requested_amount_policy` (`capacity_checked` or `context_only`). When
present, principal plus interest, total repayment and schedule sums must agree
within the same tolerances as below. Older/default results can omit this field.
Annuity fallback is labeled as annuity in the browser; the equal-payment
comparison divides actual scheduled repayments by term and is not another offer.

The candidate requires month-end cutoffs in December 2019–December 2028,
never future dates, and at least six complete history months. It discloses missing
category/counterparty metadata and purely synthetic training. Safe bounded
refusals for history/calendar/input limits are shown as actionable upstream
errors and persisted with null results. Unknown upstream errors remain generic.
See the [review](../teammate-ml-review.md) for findings, artifact/audit identity and
the reason the real-revenue blend remains the default.

The adapter validates the full response before showing any recommendation.
Positive recommended principal requires positive total payments; zero principal
requires zero total payments. For `zero_interest_mvp`, their totals agree within
relative tolerance **1e-9** and absolute tolerance **1e-12**. Valid interest-bearing
replacement policies remain supported.
An absent service returns 503; a timeout returns 504; malformed, oversized, or
mismatched output returns an upstream error. Each accepted analysis request is
persisted with its input hash, API request ID, date, result/model metadata or
failure, and audit events. No fallback hardcoded response is returned.

Every final review includes an officer name, reasoning, and timestamp. Decisions
are human actions, do not originate loans, and cannot be made on failed assessments.

## Frontend/backend routes

| Method | Route                              | Purpose                                     |
| ------ | ---------------------------------- | ------------------------------------------- |
| GET    | `/api/health`                      | Database health and ML configuration status |
| GET    | `/api/businesses`                  | Active business summaries                   |
| GET    | `/api/businesses/:id`              | History and transactions                    |
| POST   | `/api/businesses`                  | Import user-provided UZS history            |
| POST   | `/api/assessments`                 | Analyze stored business history             |
| GET    | `/api/assessments?business_id=...` | Assessment history                          |
| GET    | `/api/assessments/:id`             | Full assessment and latest decision         |
| POST   | `/api/assessments/:id/decisions`   | Record a human review                       |
| GET    | `/api/audit?business_id=...`       | Audit history                               |

The browser receives the full updated assessment after recording a decision.
The API uses `application/problem+json` errors with a request ID and safe details.
Swagger is available at `/api/docs`.
