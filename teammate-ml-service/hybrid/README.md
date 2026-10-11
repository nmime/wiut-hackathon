# Final merged financial scorer

The real-revenue provider supplies twelve aligned point forecasts and a 12 × 99
quantile grid calibrated on **development revenue only**, with model/data/source
identity. The frozen incumbent remains the revenue source unless a replacement
passes the separately frozen gates. The scorer does not train or choose models.
Future expenses use observed **total outflow** projection. Debt already present
in those unclassified outflows is included once; separate debt, counterparties,
own transfers and expense categories are unavailable. Revenue intervals are not
calibrated net-flow intervals or default probabilities.

`HybridEngine` verifies the existing vendor bytes and reuses its unchanged
`max_feasible_principal`, `solve_adaptive`, `annuity_payment` and `amortize`.
The wrapper replaces the original `plan_loan` recommendation: that function
starts from the present value of a fixed annuity payment even when an adaptive
schedule can afford more. Here, P10/P20 monthly budgets define a discounted
seasonal budget. The maximum offered principal must pass the **actual offered
schedule**, including interest floors, full amortization and the native payment
jump constraint. If needed a bounded binary search reduces principal until the
native solver fits. Search checks settled cent-rounded payments using integer-cent
principal candidates; both feasibility and overload counts use the same 1 UZS
tolerance. Every comparison uses identical principal, twelve months and
24% annual nominal interest (2% per month). Cent rounding is settled in the final
payment, and raw native amortization rows remain in evidence.

An automatically generated offer below 5% of its tier's discounted monthly
budget is immaterial and rejected before selecting a verdict. This prevents the
1 UZS numerical tolerance from turning near-zero principal into an affordable
loan when seasonal months have no payment budget. The scorer tries the next
tier instead. The threshold does not suppress a deliberately smaller positive
requested amount that fits an already selected material capacity; a zero request
remains unspecified.

The three advisory verdicts are:

- `affordable`: the actual offered schedule fits buffered P10 monthly budgets.
- `elevatedrisk_officer`: P20 or buffered P50 supports a material offer when
  P10 cannot. Wide P10 intervals alone never suppress a feasible positive median
  offer. An officer must explicitly assess this uncertainty.
- `decline`: fewer than six observed months, no feasible material median offer,
  nonpositive mean median surplus or at least six nonpositive median months,
  or the observed persistent-decline guard suppresses the main recommendation.
  Offered principal, payments and capacity score are then zero.

For at least eighteen observed months, the decline guard compares the latest six
months with those same calendar months one year earlier. At least five prior
positive observations must be usable; their median year-on-year ratio must be
≤ 0.8 and at least 80% of those ratios must be ≤ 0.9. A repeating seasonal dip
therefore cannot trigger it. With twelve to seventeen observations, a disclosed
fallback requires annual log slope ≤ −0.35, at least 80% falling adjacent months,
and latest-three/earliest-three mean ≤ 0.7. Histories under twelve months use
genuine annuity fallback because their own annual seasonality is unsupported.

Capacity score is the calibrated-revenue-grid fraction covering the **actual
offered payments**, conditional on the projected total outflows. It is not a
borrower default probability. Confidence remains a history/interval evidence
indicator. Native P10/P20 buffers retain their disclosed synthetic calibration;
neither their target coverage nor real borrower repayment safety is established
by the revenue-only calibration. All final decisions remain human Nest decisions.

The authenticated API calls
`assess_request(payload, provider_callable, request_id, engine=HybridEngine())`
and durably persists both `result` and supplemental `evidence` before release.
The runtime must hold one engine, call `close()` on shutdown, validate the shared
response and preserve failed attempts. The API binds the final merged financial
engine to the revenue source qualified by the separately frozen gates.

Audit evidence distinguishes `unspecified`, `fits_selected_offer`,
`exceeds_selected_capacity` and `declined_by_guard` for the requested amount.
A positive request with zero main capacity explicitly exceeds that capacity;
no counterfactual positive tier can override the decline verdict.

`backtest.compare_actual_surplus` accepts separately observed future surplus
**after freezing** an assessment, compares offered and same-principal annuity
overload months/volume, and measures no default labels. Focused tests use only
disclosed synthetic fixtures. They retain both a seasonal case where the offered
schedule wins and an unexpected flat future where it loses; these examples do
not establish real borrower performance.
