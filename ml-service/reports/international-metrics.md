# Legacy international real-revenue forecast regression

Measured 2026-10-10T20:52:12.776037+00:00 with artifact `local-v4-bf33fb45ddc3-gradient_boosting-public65`; frozen real-revenue candidate: **adaptive_revenue_10**. Reproduce with `uv run python -m capacity_ml.evaluate_international` after training the frozen artifact.

These previously reported holdouts are now **legacy regression benchmarks**, not fresh confirmatory data. Model fitting and validation still exclude their labels. The [external-provider audit](external-metrics.md) supplies the new final check.

The final audit contains **56 real series**, **4 disjoint geographic split groups** and **672 observed forecast months** (672 unique targets). Excluded final-window counts by provider and reason: `{'abs': {'missing_suppressed_or_unreliable_month': 6}, 'statcan': {'missing_suppressed_or_unreliable_month': 28}}`; [all excluded identities and reasons](international-metrics.json) remain available. Groups are separated from model fitting and candidate validation; each provider's terminal test interval follows that provider's training and validation intervals. Other countries may have later training observations.

| Forecast       | Macro window normalized MAE | sMAPE (%) | Seasonal MASE | Normalized WAPE (%) |
| -------------- | --------------------------: | --------: | ------------: | ------------------: |
| selected       |                      0.0629 |    6.0589 |        0.6766 |              6.0802 |
| seasonal_naive |                      0.0713 |    6.9645 |        0.7818 |              6.8880 |

Selected-model macro normalized MAE improvement versus fixed seasonal naive: **11.7284%**. A deterministic whole-geography bootstrap gives the descriptive 95% interval `[4.413458616870091, 16.756192512475977]` percentage points from **4 groups** (2000 usable replicates). Small group counts and correlated economic shocks limit this interval; it is not a future-accuracy guarantee.

| Provider | Series | Months | Selected normalized MAE | Naive normalized MAE | Selected raw MAE (provider units) | Selected WAPE (%) |
| -------- | -----: | -----: | ----------------------: | -------------------: | --------------------------------: | ----------------: |
| abs      |     24 |    288 |                  0.0578 |               0.0686 |                           10.3439 |            3.2375 |
| statcan  |     32 |    384 |                  0.0667 |               0.0732 |                       21,960.9860 |            6.4447 |

Raw monetary errors are shown only within their original provider units. AUD and CAD errors are never pooled or converted to amount indices. Provider units, attribution, retrieval dates, snapshot hashes and fixed split dates are included in the machine-readable report.

- [Australian Bureau of Statistics: Retail Trade, Australia, June 2025; Table 11 original turnover by state and industry subgroup](https://www.abs.gov.au/statistics/industry/retail-and-wholesale-trade/retail-trade-australia/jun-2025) — **million AUD, current prices**, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Retrieved 2026-10-10; raw source SHA256 `13853143285f65c1d368c51b81e9bf83aab1d9613dac1c091e0dd38e6c64ae5c`.
- [Statistics Canada: Table 20-10-0056-01 Monthly retail trade sales by province and territory](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2010005601) — **thousand CAD, current prices**, [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence). Retrieved 2026-10-10; raw source SHA256 `eb3ba0e000bb96c321de3bb28b3269671c44e0f04010a75a41f510a8eb978e2b`.
- `abs`: training targets through 2023-06; validation 2023-07–2024-06; terminal final audit 2024-07–2025-06. All leaf sector records from one state/province share a split.
- `statcan`: training targets through 2024-07; validation 2024-08–2025-07; terminal final audit 2025-08–2026-07. All leaf sector records from one state/province share a split.

Predetermined engineering acceptance: **PASS**. Overall macro normalized MAE must improve versus seasonal naive and no provider may worsen more than 10%. Measured provider improvements: `{'abs': 15.794599568644507, 'statcan': 8.870215188927977}`. These guardrails were fixed before reading final labels; they do not certify lending or default predictions.

| History length          | Cases | Selected normalized MAE | Naive normalized MAE |
| ----------------------- | ----: | ----------------------: | -------------------: |
| long_at_least_24_months |    56 |                  0.0629 |               0.0713 |

Provider, sector and each 1–12-month forecast-horizon breakdowns are preserved in [the full machine-readable audit](international-metrics.json). Empty short-history slices are omitted rather than claimed as validated. Overlapping targets are counted separately as forecast tasks and explicitly deduplicated as observations.

Primary comparisons use historical-scale-normalized absolute error. Raw MAE and WAPE are computed within each provider's declared units only, never pooled across AUD/CAD. sMAPE assigns exactly zero error to actual=forecast=0; all other observations are included. Seasonal MASE divides by mean absolute 12-month differences in the input history only, with undefined short or constant histories reported. WAPE includes zero and near-zero months; an all-zero actual denominator is undefined.

MASE in the selected forecast includes 672 months, excluding 0 windows with fewer than 13 history months and 0 windows with a zero seasonal denominator. WAPE excludes **zero months**; all-zero denominators are undefined. sMAPE has 0 exactly zero/zero forecast-target pairs, assigned zero error.

These ABS/Canada terminal labels were reported during the previous model upgrade, so this is now a legacy regression benchmark, not fresh confirmation. Labels remain excluded from fitting and validation selection. Fixed seasonal naive is the comparison. The separately reserved external-provider audit supplies new evidence.

All sectors of a geography share an entity group. Related sectors and regions remain correlated through national economic shocks; clustered intervals from the small number of final geographies are descriptive. Time boundaries are provider-specific: other countries can have training observations later than an international test date, so this is not a globally chronological future holdout. Provider snapshots use one current revision vintage, not unrevised observations available at each historical date. International aggregate turnover can differ materially from an individual borrower's bank receipts.

Licensed real aggregate revenue only. No real borrower expense, payment-capacity, repayment or default outcomes are available. This forecast evaluation does not validate lending decisions.
