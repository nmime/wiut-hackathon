# Final model and fresh revenue replacement evidence

The product now has one final local scorer: the frozen real-trained incumbent revenue forecast, an observed-total-outflow projection, a real development-residual revenue grid, and the teammate's unchanged seasonal amortization primitives at 24% nominal annual interest. The improved third model remains a measured research candidate. It did not meet the replacement threshold.

The best predefined candidate was **75% incumbent + 25% improved LightGBM**, using damped seasonal anchors, log residuals and 15 leaves. Eight models and 32 mixtures were compared on development data; no candidate reached the predeclared 5% improvement with all guards. Only the frozen best guarded candidate received the new holdout scores. No subsequent model tuning or threshold relaxation was performed.

## Actual forecast results

The metric is mean absolute forecast error divided by each case's mean revenue over its latest up-to-twelve observed months, averaged equally across cases within each provider and then equally across providers. It is dimensionless and is not borrower default accuracy. Lower is better.

| Forecast component      | Primary fresh panel: 454 windows / 5,448 months | Latest year: 127 windows / 1,524 months |
| ----------------------- | ----------------------------------------------: | --------------------------------------: |
| Frozen incumbent        |                                        0.099779 |                                0.069710 |
| Frozen improved blend   |                                    **0.097602** |                            **0.068777** |
| Previous third LightGBM |                                        0.098812 |                                0.069368 |
| Seasonal naive          |                                        0.121036 |                                0.077670 |

The improved blend reduces primary error by **2.181%** and latest-year error by **1.338%**. Its development improvement is **1.557%** on 918 full-history windows. The paired 2,000-resample annual-block diagnostic interval for the primary improvement is **[1.250%, 2.998%]**, using the nine years 2017–2025. The interval preserves case weights and paired cross-country year shocks; remaining serial, survey and revision dependence prevents an independent-borrower or prospective guarantee.

The 5% development, primary and latest-year gates fail. Provider regression guards, short-history guards, positive lower interval and valid-output checks pass. Retaining the incumbent point forecast follows the protocol fixed before comparative results. A small measured improvement is useful research evidence but does not satisfy the user's condition of a clear replacement win.

With only 3, 6 or 12 historical months, the improved candidate beats the incumbent but remains worse than seasonal naive: respectively 0.158358 vs 0.124491, 0.172622 vs 0.131184 and 0.156511 vs 0.121036. Short-history forecasting remains a documented weakness. Those labels are now consumed and cannot be reused as fresh evidence for a new routing rule.

## Data and separation

- **New training:** Statistics Canada's licensed Table 20-10-0074-01 wholesale sales, in native thousands of CAD, unadjusted nominal values. Eight geographies supply training/development; five entire geographies are reserved for the audit. The snapshot contains 416 disjoint geography/industry series. Valid new training provides 3,812 origins and 45,744 target-month examples.
- **New independent provider:** Stats NZ electronic card transactions, eight disjoint industries in native millions of NZD including GST. This measures card expenditure as an aggregate revenue proxy. It supplies only holdout data, with nine annual windows per industry and no training or calibration contribution.
- **Bounded improved training:** 11,060 origins, 132,720 target examples before history-view augmentation, 55,987 unique target coordinates and 524,532 augmented rows. Repeated history views are not new real observations. Earlier Uzbekistan, ABS, Canadian retail and Eurostat training remains explicit; old benchmark test panels are now development evidence.
- **Fresh holdout:** 527 full windows / 6,324 monthly targets overall. The primary panel has 382 Canadian audit-geography windows and 72 NZ windows. The latest panel has 119 Canadian and eight NZ windows. Missing, confidential or unreliable-required windows are excluded, including 1,241 proposed holdout windows. No missing labels become zero sales.
- **Frozen incumbent serving:** still its original 7,248 training origins, 86,976 target examples and 43,705 unique target observations. New experiment training counts are not attributed to it.

No new target coordinate overlaps the earlier development, old benchmark, fitting or calibration targets. The reservation and source snapshots were hashed before comparative errors. These are retrospective, revised-vintage aggregate series; they do not establish performance on individual Uzbek borrowers. Canada was already a training country through retail; wholesale is a fresh dataset/sector partition. NZ is a fresh provider/country. The attempted US Census source was excluded before fitting and errors because the official download was unavailable and the alternate redistributor did not authorize this ML use.

Publisher/licence links and exact download/hash metadata are preserved in the snapshots and JSON report: [Statistics Canada wholesale](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2010007401), [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/reference/licence), [Stats NZ August 2026 card transactions](https://www.stats.govt.nz/information-releases/electronic-card-transactions-august-2026/). Native monetary values supply scale-normalized patterns; they are never silently converted to borrower UZS.

## Real revenue interval coverage

The .01–.99 grid uses signed, historical-scale-normalized real development residuals, balanced across providers and split by history support and forecast horizon. Median offsets remain zero. The 68 old external-audit windows and all their 272 history views are excluded from this residual calibration. Calibration contains 3,208 dependent history views; bucket counts disclose both residual samples and unique target coordinates.

| Incumbent revenue grid                               | Actual at/above P10; nominal 90% | Actual at/above P20; nominal 80% | Actual inside P10–P90; nominal 80% |
| ---------------------------------------------------- | -------------------------------: | -------------------------------: | ---------------------------------: |
| Old 68-window external diagnostic: 816 pooled months |                          98.652% |                          97.304% |                            81.618% |
| Fresh Canadian wholesale: 4,584 months               |                          94.961% |                          90.118% |                        **70.724%** |
| Fresh NZ: 864 months                                 |                          97.338% |                          95.949% |                            87.037% |

The lower bounds are conservative in these panels. The Canadian central interval undercovers its nominal 80% target; this result is retained and is not repaired using the final labels. The 68-window result is a consumed diagnostic, because point-model selection previously used those outcomes. Neither this grid nor the inherited synthetic payment buffers provide calibrated expense, net-flow, repayment or default probabilities.

## Why the final components were chosen

| Component          | Final choice                                                      | Evidence and behavior                                                                                                     |
| ------------------ | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Median revenue     | Frozen incumbent real-trained model                               | Preserves measured artifact; new blend's 2.181% fresh gain misses the 5% promotion threshold                              |
| Future expenses    | Observed-total-outflow projection                                 | Public revenue sources supply no expense labels with which to validate the synthetic teammate expense booster             |
| Revenue bounds     | Frozen real development-residual grid                             | Actual P10/P20 coverage is recorded above; aggregate transfer and central-band undercoverage remain explicit              |
| Financial engine   | Frozen teammate amortization/seasonal solver                      | 24% APR, genuine interest, twelve monthly payments; same actual budget determines both principal and the offered schedule |
| Verdict            | Affordable / elevated risk for officer / decline                  | A feasible positive median receives elevated-risk review when P10/P20 alone cannot support it                             |
| Decline protection | Observed same-month year-on-year guard and median viability guard | Sustained declining and six-nonpositive-median-month fixtures receive zero principal and score                            |
| Score              | Modeled grid coverage of the actual offered payments              | Zero offer has zero score; elevated P50 reliance remains explicit, without a synthetic population capacity predictor      |
| Requested amount   | Checked against chosen schedule's capacity                        | Audit distinguishes unspecified, fitting, exceeding and guard-declined requests                                           |

The final service validates input and output, verifies exact bundle/artifact/calibration/report SHA-256 before deserialization, pins its combined dependency environment, and persists the full financial evidence before releasing a result. Inference requires no external API. Every assessment and officer decision retains the existing audited contract; officers record final decisions.

## Financial proof and limits

[The disclosed synthetic financial backtest](final-financial-behavior.md) retains both favorable and adverse cases at identical principal, 24% rate and twelve-month term. The expected seasonal future overloads **0** months with the offered plan versus **7** with equal payments. An unexpected flat future overloads **4** versus **0**. The wide-band positive median gets an elevated-risk P50 offer; sustained decline gets zero. Interest totals reconcile with principal and payments.

This is behavioral/accounting proof. The public datasets contain no actual borrower costs, repayment or default outcomes; a real free-cash-flow backtest cannot be claimed. No synthetic fixture was imported into an active portfolio. Missing actual borrower expense/repayment labels and weak short-history forecasting remain the next data needs.

## Reproduction and preserved evidence

- Preregistered rules: `docs/revenue-upgrade-protocol.md` and `ml-service/data/fresh-holdout-reservation.json`.
- Machine evidence and every saved actual/prediction: `revenue-upgrade-fresh.json` and `revenue-upgrade-fresh-predictions.json`.
- Bounded trainer: `teammate-ml-service/benchmark/improved_revenue.py`; experiment phases: `python -m benchmarks.fresh_experiment prepare|select|terminal|report` in the frozen `ml-service` environment, with training/inference in the frozen teammate environment. Preparation requires an empty output and the preserved previous benchmark artifact directory; selected-only terminal inference uses the variant frozen by `select`.
- Exact default bundle: `ml-service/final_model/artifacts/bundle.json`; `python -m benchmarks.package_final` verifies measured component hashes and packages without fitting. Runtime startup also verifies the source-controlled release hash. Hashed frozen asset JSON is deliberately excluded from automatic formatting.
- Runtime and tests: `docs/final-model-runtime.md`; `pnpm test:final-ml` exercises the actual assembled scorer through Nest and the browser. The original model code, model evidence and teammate vendor bytes remain preserved for comparison.

All final labels are now consumed. Future research must reserve another independent holdout before any claim of a new confirmatory improvement. This work changes the topic branch default; it does not merge or deploy the branch.

Validation completed on 11 October 2026 with Node 24.18.0 and pnpm 12.8.1: `pnpm check` passed typechecks, 63 contract/API/import unit tests, builds and the repository formatting check. Python suites passed 190 original/revenue-evidence tests, 78 teammate/financial tests and 16 final runtime/provider tests. Existing API/browser checks passed 19/19, historical real and teammate integration passed 5/5 and 8/8, and the final assembled scorer passed 5/5 API/browser tests including mobile layout and durable officer decisions. Production Docker build and smoke with external networking disabled passed. Final measured assembly identity is `final-v1-5f3ac942cdb9ce34`. Ruff and `git diff --check` passed.
