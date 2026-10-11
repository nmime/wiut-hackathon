# ML integration contract

The browser calls NestJS; Nest alone calls the private final Python `/score`
endpoint. Product Compose connects to `http://ml:8000` and serves
`final_model.api:app`. The local development script uses loopback port 8110.
`ML_TIMEOUT_MS` defaults to 8000. Inference uses no external API.
See [final runtime](final-model-runtime.md) for verified component identities.

## Request and units

```json
{
  "business_id": "business-id",
  "requested_amount": null,
  "currency": "UZS",
  "as_of_date": "2026-09-30",
  "transactions": [
    {
      "ts": "2026-09-01T12:00:00Z",
      "direction": "in",
      "channel": "qr",
      "amount_index": 2500000
    }
  ]
}
```

This single illustrative row explains the schema, not borrower evidence.
The API filters the business's transactions to the requested cutoff and rejects
an empty selected history. Timestamps may use Z, a timezone offset, or no offset
(interpreted as UTC). Allowed channels are `card`, `transfer`, `qr`, `cash_in`,
and `other`; directions are `in` and `out`. Each positive amount must be finite
and within 1e-12–1e12. Histories contain 1–20,000 rows.

For actual UZS imports, **1 amount_index = 1 UZS**. Nest snapshots the amount unit
on the business and assessment. Historical indexed records preserve their original
unit. `requested_amount` is nullable and nonnegative; the final model checks a
positive request against the offered schedule's capacity. A zero request is
treated as unspecified and flagged. Its `requested_amount_policy` is
`capacity_checked`.

The final scorer supports partial-month cutoffs; the incomplete month does not
become a completed forecast input. Short histories receive explicit warnings.
Fewer than six complete history months produce no positive recommendation.
A twelve-month forecast begins after the assessment month. Calendar and finite
value bounds are validated, rather than silently inventing history.

## Response

The source of truth is
[`ScoreResponseSchema`](../libs/common/api-contracts/src/index.ts).
Python and Nest validate the response before displaying or saving a result.

| Field                                | Meaning                                                                    |
| ------------------------------------ | -------------------------------------------------------------------------- |
| `capacity_score`                     | Payment-capacity indicator 0–100; not default probability                  |
| `score_band`                         | `low`, `medium`, or `high`                                                 |
| `cashflow_summary`                   | Historical inflow, net surplus, volatility and trend                       |
| `recommended_loan`                   | Offered principal, installment summary, term and rationale                 |
| `seasonality.monthly_forecast_index` | Twelve future monthly median net-flow values                               |
| `adaptive_schedule`                  | Actual monthly payments for the recommended principal                      |
| `explanation`                        | Capacity factors, narrative and advisory information                       |
| `confidence`                         | Evidence indicator in 0–1, not a repayment probability                     |
| `forecast_provenance`                | Actual forecast composition, cost policy and training count                |
| `loan_terms`                         | Annual rate, plan type, total interest, total repayment and request policy |
| `flags`                              | Advisory verdict and disclosed limits                                      |
| `model_version`, `request_id`        | Nonempty identifiers retained in audit                                     |

The final assembly returns exactly one advisory verdict flag:
`verdict_affordable`, `verdict_elevated_risk`, or `verdict_decline`.
Decline guards produce zero principal and score. A positive median can produce
an elevated-risk offer when lower revenue bounds cannot support a main-tier offer;
the officer decides whether to accept that risk.

The rate is **24% nominal annual / 2% monthly**, with a twelve-month term.
Affordability and the seasonal schedule share the same actual monthly budgets.
Principal plus interest equals total repayment; scheduled payments reconcile with
that total. Invalid or contradictory output fails the assessment. The frontend's
equal-payment comparator is calculated at the same principal, rate and term; it
is not a second offer.

Final provenance reports `real_revenue_weight: 1` and
`synthetic_net_weight: 0`, with an observed-total-outflow projection. Forecast
weights describe composition, not accuracy. The frozen incumbent was trained on
86,976 overlapping target examples / 43,705 unique revenue observations.
The new research experiment's additional training is not attributed to it.
Older persisted responses may omit provenance or loan terms and remain supported.

## Failure, audit and human review

A disconnected service returns 503; a timeout returns 504. Invalid, oversized,
mismatched or nonfinite upstream output is rejected. Each accepted assessment
attempt persists the input hash, cutoff, authenticated actor, API request ID and
either the validated result or failure. Missing ML never causes a hardcoded result.

The final service verifies its assets and source identities at startup and fails
closed if a component differs. Its private `/health` reports the complete assembly
hash, component hashes and loaded model version. Its durable audit records every
direct scoring attempt. Successful events retain the financial evidence and
validated response before release; audit failure returns 503. Do not expose the
ML audit to the public web.

Only the authenticated officer records approval, decline or a request for more
information with reasoning. Decisions remain tenant scoped, immutable and audited.
They do not originate a loan. Failed attempts cannot receive a final decision.

## Application routes

| Method | Route                              | Purpose                                 |
| ------ | ---------------------------------- | --------------------------------------- |
| GET    | `/api/health`                      | Database readiness and ML configuration |
| GET    | `/api/businesses`                  | Active workspace's business summaries   |
| GET    | `/api/businesses/:id`              | History and transactions                |
| POST   | `/api/businesses`                  | Validated UZS import                    |
| POST   | `/api/assessments`                 | Analyze stored business history         |
| GET    | `/api/assessments?business_id=...` | Assessment history                      |
| GET    | `/api/assessments/:id`             | Assessment and recorded decision        |
| POST   | `/api/assessments/:id/decisions`   | Record human review                     |
| GET    | `/api/audit?business_id=...`       | Tenant-scoped audit                     |

Public API health indicates configuration, not successful model inference.
The actual final integration suite verifies inference through Nest and the browser.
Swagger is available at `/api/docs`. Errors use `application/problem+json` with
safe details and a request ID.

Historical 0% scorer and synthetic teammate policies are retained in
[archived contract notes](research/historical-ml-contract.md) and
[research reproduction](research/README.md); they do not configure production.
