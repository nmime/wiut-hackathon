# Fresh international real-revenue forecast audit

Measured 2026-10-10T19:29:35.487313+00:00 with artifact `local-v3-90057d5d69d7-gradient_boosting-public10`; frozen real-revenue candidate: **history_shrinkage_50**. Reproduce with `uv run python -m capacity_ml.evaluate_international` after training the frozen artifact.

The final audit contains **56 real series**, **4 disjoint geographic split groups** and **672 observed forecast months** (672 unique targets). Excluded final-window counts by provider and reason: `{'abs': {'missing_suppressed_or_unreliable_month': 6}, 'statcan': {'missing_suppressed_or_unreliable_month': 28}}`; [all excluded identities and reasons](international-metrics.json) remain available. Groups are separated from model fitting and candidate validation; each provider's terminal test interval follows that provider's training and validation intervals. Other countries may have later training observations.

| Forecast       | Macro window normalized MAE | sMAPE (%) | Seasonal MASE | Normalized WAPE (%) |
| -------------- | --------------------------: | --------: | ------------: | ------------------: |
| selected       |                      0.0663 |    6.3940 |        0.7176 |              6.4060 |
| seasonal_naive |                      0.0713 |    6.9645 |        0.7818 |              6.8880 |

Selected-model macro normalized MAE improvement versus fixed seasonal naive: **6.9980%**. A deterministic whole-geography bootstrap gives the descriptive 95% interval `[-2.091383734459007, 15.396892680606488]` percentage points from **4 groups** (2000 usable replicates). Small group counts and correlated economic shocks limit this interval; it is not a future-accuracy guarantee.

| Provider | Series | Months | Selected normalized MAE | Naive normalized MAE | Selected raw MAE (provider units) | Selected WAPE (%) |
| -------- | -----: | -----: | ----------------------: | -------------------: | --------------------------------: | ----------------: |
| abs      |     24 |    288 |                  0.0581 |               0.0686 |                           11.0093 |            3.4458 |
| statcan  |     32 |    384 |                  0.0724 |               0.0732 |                       23,478.1163 |            6.8899 |

Raw monetary errors are shown only within their original provider units. AUD and CAD errors are never pooled or converted to amount indices. Provider units, attribution, retrieval dates, snapshot hashes and fixed split dates are included in the machine-readable report.

- [Australian Bureau of Statistics: Retail Trade, Australia, June 2025; Table 11 original turnover by state and industry subgroup](https://www.abs.gov.au/statistics/industry/retail-and-wholesale-trade/retail-trade-australia/jun-2025) — **million AUD, current prices**, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Retrieved 2026-10-10; raw source SHA256 `13853143285f65c1d368c51b81e9bf83aab1d9613dac1c091e0dd38e6c64ae5c`.
- [Statistics Canada: Table 20-10-0056-01 Monthly retail trade sales by province and territory](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2010005601) — **thousand CAD, current prices**, [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence). Retrieved 2026-10-10; raw source SHA256 `eb3ba0e000bb96c321de3bb28b3269671c44e0f04010a75a41f510a8eb978e2b`.
- `abs`: training targets through 2023-06; validation 2023-07–2024-06; terminal final audit 2024-07–2025-06. All leaf sector records from one state/province share a split.
- `statcan`: training targets through 2024-07; validation 2024-08–2025-07; terminal final audit 2025-08–2026-07. All leaf sector records from one state/province share a split.

Predetermined engineering acceptance: **PASS**. Overall macro normalized MAE must improve versus seasonal naive and no provider may worsen more than 10%. Measured provider improvements: `{'abs': 15.396892680606477, 'statcan': 1.0943464907942069}`. These guardrails were fixed before reading final labels; they do not certify lending or default predictions.

| History length          | Cases | Selected normalized MAE | Naive normalized MAE |
| ----------------------- | ----: | ----------------------: | -------------------: |
| long_at_least_24_months |    56 |                  0.0663 |               0.0713 |

Provider, sector and each 1–12-month forecast-horizon breakdowns are preserved in [the full machine-readable audit](international-metrics.json). Empty short-history slices are omitted rather than claimed as validated. Overlapping targets are counted separately as forecast tasks and explicitly deduplicated as observations.

Primary comparisons use historical-scale-normalized absolute error. Raw MAE and WAPE are computed within each provider's declared units only, never pooled across AUD/CAD. sMAPE assigns exactly zero error to actual=forecast=0; all other observations are included. Seasonal MASE divides by mean absolute 12-month differences in the input history only, with undefined short or constant histories reported. WAPE includes zero and near-zero months; an all-zero actual denominator is undefined.

MASE in the selected forecast includes 672 months, excluding 0 windows with fewer than 13 history months and 0 windows with a zero seasonal denominator. WAPE excludes **zero months**; all-zero denominators are undefined. sMAPE has 0 exactly zero/zero forecast-target pairs, assigned zero error.

Final labels are used only by this evaluator after model candidate and transfer selection are frozen. Fixed seasonal naive is the comparison, not another selected candidate. No fitting, tuning or selection occurs here. Previously inspected Uzbekistan and synthetic tests are separate legacy regression benchmarks.

All sectors of a geography share an entity group. Related sectors and regions remain correlated through national economic shocks; clustered intervals from the small number of final geographies are descriptive. Time boundaries are provider-specific: other countries can have training observations later than an international test date, so this is not a globally chronological future holdout. Provider snapshots use one current revision vintage, not unrevised observations available at each historical date. International aggregate turnover can differ materially from an individual borrower's bank receipts.

Licensed real aggregate revenue only. No real borrower expense, payment-capacity, repayment or default outcomes are available. This forecast evaluation does not validate lending decisions.
