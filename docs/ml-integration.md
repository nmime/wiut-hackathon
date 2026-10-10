# ML integration contract

The React application calls NestJS. Only NestJS communicates with the Python
service. Set `ML_SERVICE_URL` to the service base URL; the adapter appends `/score`.
`ML_TIMEOUT_MS` defaults to 8000. Scoring, forecasting, and model inference must
operate locally within the bank perimeter in a production implementation.

The optional service in `ml-service` implements this contract locally. Run the
complete stack with the `docker-compose.ml.yml` override, or point the adapter
at the teammate's service. Default frontend/backend development still works
with ML disconnected. See `ml-service/README.md` for training and evaluation.

## Request

```json
{
  "business_id": "synthetic-business-id",
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
in the supplied brief. The transactions use standardized amount indices.
No currency conversion is assumed. The ML team must clarify how a currency
request constrains an indexed recommendation before using that comparison.
The default analysis omits the requested amount by sending `null`.

Allowed channels: `card`, `transfer`, `qr`, `cash_in`, `other`. Amounts must be
finite and positive. Histories contain 1–20,000 transactions. Timestamps support
ISO timestamps with `Z`, timezone offset, or no offset (interpreted as UTC).
NestJS selects transactions on or before the assessment date. An empty selected
history is rejected. The business and date in the result must match the request.

## Optional local service limits

The teammate's transport contract remains the source of truth. The optional
implementation in `ml-service` supports a narrower calendar window: at most
240 inclusive calendar months from the earliest transaction month through the
assessment month, and assessment years 0001–9998. The 12 forecast months must
fit within the supported calendar. These implementation limits do not tighten
the general NestJS/shared transport contract. Unsupported inputs return HTTP
422 from the optional service; NestJS records the failed assessment and returns
an upstream error.

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

| Field                                      | Meaning                                                                 |
| ------------------------------------------ | ----------------------------------------------------------------------- |
| `capacity_score`                           | Number 0–100, payment capacity, not default probability                 |
| `score_band`                               | `low`, `medium`, or `high`                                              |
| `cashflow_summary`                         | Mean inflow index, volatility, net surplus index, trend                 |
| `recommended_loan`                         | Nonnegative indexed principal/installment, term 1–120 months, rationale |
| `seasonality.monthly_forecast_index`       | Exactly 12 future monthly net-flow indices, may be negative             |
| `seasonality.weak_months`, `strong_months` | Calendar month numbers 1–12; unique and disjoint                        |
| `adaptive_schedule`                        | One-based contiguous month offsets, indexed installments, notes         |
| `explanation.top_factors`                  | Factor names, positive/negative impact, finite weights                  |
| `explanation.advisory`                     | Advice strings                                                          |
| `confidence`                               | Fraction 0–1, displayed as a percentage                                 |
| `flags`                                    | Known failure and uncertainty warning strings                           |
| `model_version`, `request_id`              | Nonempty audit identifiers                                              |

The 12 forecast values correspond to the next 12 calendar months after the
assessment month. A positive principal requires a schedule matching the
suggested term. Zero-capacity recommendations may have an empty schedule.
Weak months should receive reduced payments; stronger months may receive increased
payments, within the model's affordable capacity constraints.

## Error and audit behavior

The adapter validates the full response before showing any recommendation.
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
| GET    | `/api/businesses`                  | Synthetic business summaries                |
| GET    | `/api/businesses/:id`              | History and transactions                    |
| POST   | `/api/businesses`                  | Import explicitly synthetic history         |
| POST   | `/api/assessments`                 | Analyze stored business history             |
| GET    | `/api/assessments?business_id=...` | Assessment history                          |
| GET    | `/api/assessments/:id`             | Full assessment and latest decision         |
| POST   | `/api/assessments/:id/decisions`   | Record a human review                       |
| GET    | `/api/audit?business_id=...`       | Audit history                               |

The browser receives the full updated assessment after recording a decision.
The API uses `application/problem+json` errors with a request ID and safe details.
Swagger is available at `/api/docs`.
