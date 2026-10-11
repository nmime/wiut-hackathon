# ML model comparison

Reviewed 11 October 2026. Both frozen models are deployed privately. The
real-revenue blend is selected for the app; the teammate candidate can be selected
through the deployment configuration. Neither model predicts borrower default or
automatically makes a lending decision.

## What changes for an officer

| Question                                     | Default real-revenue blend                                                                                                                                     | Teammate candidate                                                                                                                                                                    |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Where does training data come from?          | Licensed Uzbekistan, Australian, Canadian and European revenue observations, plus separate synthetic borrower components                                       | Generated histories for 420 training businesses and 91 validation businesses; no actual borrower training                                                                             |
| How much real data is used?                  | 86,976 rolling revenue training targets, representing 43,705 unique target observations; these are aggregate time series, not that many borrowers              | 65,709 supervised synthetic training rows; public calendar features do not make the financial training data real                                                                      |
| How is the forecast built?                   | Histogram gradient boosting with revenue residual experts and seasonal/harmonic baselines; observed costs; a separately trained synthetic net-flow branch      | Two LightGBM models forecast incoming revenue and operating expenses; calendar/Ramadan, history and industry features                                                                 |
| What blend is served?                        | Established stable histories: 65% real-revenue/observed-cost forecast plus 35% synthetic net forecast; short or changed histories: 25% real plus 75% synthetic | Entire financial model is synthetic-trained; structured provenance discloses 0% public-revenue contribution                                                                           |
| Are forecast intervals available?            | Point forecasts and heuristic evidence confidence; no calibrated prediction interval                                                                           | Native P10/P50/P90 forecasts and a conservative P10 payment tier; detailed native intervals remain in the private ML audit                                                            |
| How does the score work?                     | Explicit financial/evidence factors and viability guards produce a 0–100 capacity indicator                                                                    | Modeled synthetic free-cash-flow coverage of a learned reference load produces a 0–100 capacity indicator                                                                             |
| What is the interest policy?                 | Explicit 0% MVP policy; payments sum to principal                                                                                                              | Genuine 24% annual interest, with interest, principal and balance calculations retained                                                                                               |
| What repayment plans are used?               | Twelve adaptive monthly payments capped by buffered positive forecast surplus                                                                                  | Genuine adaptive or annuity plan; the product adapter retains a twelve-month term                                                                                                     |
| Does a requested amount constrain the offer? | Context only; the model discloses that it does not cap its recommendation                                                                                      | Checked against native capacity; excessive requests trigger a second genuine assessment for the conservative main-tier recommendation                                                 |
| What history is required?                    | Short histories can produce a low-confidence illustrative forecast; fewer than six active months or inadequate evidence suppress a positive loan               | Fewer than six complete months is refused; six–eleven months uses annuity fallback; twelve–twenty-three months has reduced seasonal support; twenty-four or more has full native mode |
| Can an officer assess midmonth?              | Yes; an incomplete month is excluded from features, with a disclosed partial-only fallback                                                                     | No; the bridge requires a completed month-end so forecasts and repayments remain aligned                                                                                              |
| What is the supported calendar?              | Bounded calendar/history validation, without the teammate's Ramadan-table restriction                                                                          | Completed cutoffs in December 2019–December 2028, never future dates; native calendar covers 2018–2029                                                                                |
| Who makes the final decision?                | Authenticated officer in Nest, scoped to their tenant                                                                                                          | The same authenticated Nest workflow; original vendor public decision routes are excluded                                                                                             |

The forecast weights describe composition, **not percentages of correct
predictions**. Aggregate public revenues do not supply actual borrower expense,
repayment or default labels. Both confidence values are evidence indicators,
rather than calibrated real-borrower success probabilities. Different score
definitions and band thresholds mean the scores should not be ranked as though
they were the same measurement.

The minimal import contract provides timestamp, direction, channel and amount.
It contains no transaction category, counterparty or debt classification. The
candidate cannot establish own transfers, separated debt payments or customer
concentration from fields that were never supplied. The adapter discloses these
missing inputs instead of inventing them.

## What the validation actually shows

The default model's frozen external revenue audit used **68 actual series and
816 future months in six usable country clusters**, with reserved European
countries and the entire UK ONS provider excluded from fitting and selection.
Normalized revenue MAE was **19.304% lower than seasonal naive**. This supports
that particular aggregate revenue forecasting task; it is not 80.696% accuracy
and does not establish borrower expense or repayment performance. Short-history
stress slices performed worse than the seasonal baseline.

Its separately frozen synthetic engineering audit evaluated **900 businesses
and 10,800 future net-flow months**. Normalized net-flow MAE improved about
**5.478%** over the fixed synthetic reference. Pattern-break error worsened
about **10.994%**, within the preset 15% cohort tolerance. This was the fourth
exploratory cycle after three retained rejections; the audit is now consumed.
The server's exact deployed artifact passed all five unchanged engineering
gates. Strict reproduction of the original Mac metrics **failed** with retained
small numerical differences; portable qualification passed. This is a
same-recipe regression check, not another fresh validation set.

The teammate's **author-supplied** reports show inflow WAPE of **21.8%** on
seeds 42–44 and **18.6%** on seeds 45–47; free-flow WAPE is **44.1%** and
**39.8%**. Nominal 80% forecast intervals covered **75.2%** and **76.6%**, so
they under-covered. Declining businesses performed worse than ETS. These full
training/evaluation runs were not independently reproduced during integration.
Industry priors used before grouped calibration folds include held-out-fold
histories, and the control seeds were examined before the final formula change.
These limitations are preserved in the independent review.

The above error numbers measure different targets, units, cohorts and policies.
**They do not prove either model is more accurate than the other.** A replacement
decision needs both fixed artifacts evaluated against the same unseen histories
and observed future outcomes, with forecast error, interval coverage, refusal
rate and capacity checks declared in advance. Repayment comparisons must use
the same principal, term and interest rate. Real borrower validation additionally
needs observed operating costs and repayment outcomes.

## What was independently verified

- Original teammate implementation: 49 supplied tests passed.
- Private wrapper: 24 focused tests passed, including input limits, genuine
  interest totals, refusals, artifact identity and audit durability.
- Candidate integration: nine end-to-end tests through Python, Nest,
  PostgreSQL and React passed, including annuity/adaptive labels, requested
  limits, immutable human review, tenant isolation, and generated showcase
  scenarios with a persisted short-history refusal.
- Default-model integration: six end-to-end tests passed, including all six
  generated showcase scenarios, persisted model results and human review.
- Public HTTPS default-model flow verified actual scoring, saved results,
  authentication, permissions and guarded removal of temporary test records.
- Both deployed scorer identities were checked against the exact frozen
  artifacts. These are working-system checks, not accuracy measurements.

The [Showcase lab](showcase.md) generates explicitly synthetic inputs in separate
workspaces. It leaves these artifacts and validation evidence unchanged; it does
not add real training observations or establish model accuracy.

## Recommendation and sources

Keep the real-revenue blend as the default because it has relevant licensed
public-data lineage and preserved external revenue validation. Keep the
teammate candidate available for its richer uncertainty and interest-bearing
planning features, without claiming a real-data accuracy improvement. Preserve
both artifacts before collecting a common evaluation cohort.

- [Default implementation and data](../ml-service/README.md)
- [Frozen external revenue audit](../ml-service/reports/external-audit-v2-frozen.md)
- [Frozen synthetic engineering audit](../ml-service/reports/engineering-audit-v5-frozen.md)
- [Independent teammate review](teammate-ml-review.md)
- [Private candidate contract and limitations](../teammate-ml-service/README.md)
- [Production selection](deployment.md)
