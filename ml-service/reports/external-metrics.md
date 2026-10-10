# External real-revenue audit

Measured 2026-10-10T21:11:33.941827+00:00 with frozen model `local-v4-bf33fb45ddc3-gradient_boosting-public65` and real-revenue candidate **adaptive_revenue_10**. Reproduce with `uv run python -m capacity_ml.evaluate_external`.

Report status: `consumed_v2_external_regression_reproduction_unchanged_revenue_component`. The initial untouched v2 result is preserved in [external-audit-v2-frozen.json](external-audit-v2-frozen.json). Repeated runs are consumed-label regression checks, not new independent evidence.

The original frozen cohort covers **68 actual series / 816 observed future months**, representing 816 unique targets in **6 country clusters**. Six reserved Eurostat countries and the wholly unseen UK ONS provider are separated from fitting and selection. Eurostat audit Sep 2025–Aug 2026; UK ONS Sep 2025–Aug 2026. Quality exclusions by provider/reason: `{'eurostat': {'missing_suppressed_or_unreliable_month': 83}}`; full identities are retained in [JSON](external-metrics.json).

| Forecast        | Macro normalized MAE | sMAPE (%) | Normalized WAPE (%) |
| --------------- | -------------------: | --------: | ------------------: |
| Frozen selected |               0.0689 |    6.6279 |              6.5703 |
| Seasonal naive  |               0.0853 |    8.2814 |              8.1421 |

Measured macro normalized MAE improvement: **19.3041%**; whole-country bootstrap descriptive 95% interval `[15.785337107983445, 23.036554713538603]` percentage points. Resampling keeps each country's dependent sector records together. This small, correlated set cannot establish general or borrower-level accuracy.

Predetermined engineering acceptance: **PASS**. Overall normalized MAE must improve (>0%) versus seasonal naive and no provider may regress by more than 10%. Missing reserved providers fail rather than silently disappear. Actual provider improvements: `{'eurostat': 19.851973390691423, 'ons': 17.99921838254358}`; missing providers: `[]`.

| Provider | Actual series | Future months | Selected normalized MAE | Naive normalized MAE | Selected raw MAE (provider index points) |
| -------- | ------------: | ------------: | ----------------------: | -------------------: | ---------------------------------------: |
| eurostat |            49 |           588 |                  0.0669 |               0.0834 |                                   7.7258 |
| ons      |            19 |           228 |                  0.0741 |               0.0903 |                                   7.3225 |

- [European Commission, Eurostat: Turnover and volume of sales in wholesale and retail trade - monthly data (sts_trtu_m), NETTUR only](https://ec.europa.eu/eurostat/databrowser/view/sts_trtu_m/default/table?lang=en) — **nominal net turnover index, 2021=100 (I21), unadjusted (NSA)**; [Eurostat reuse policy (Decision 2011/833/EU)](https://ec.europa.eu/eurostat/help/copyright-notice); raw SHA256 `f1b2dc21f1c08bd5b5381ea94bbd9f4003a281cf6560b2e1726ed05afaa75c84`.
- [Office for National Statistics: Retail Sales Index DRSI, Great Britain, nominal unadjusted all-business value indices](https://www.ons.gov.uk/businessindustryandtrade/retailindustry/datasets/retailsales/current) — **nominal retail sales value index, 2024=100, not seasonally adjusted**; [Open Government Licence v3.0](https://www.ons.gov.uk/help/terms-conditions); raw SHA256 `108ab85beb07dd3b679fab8d2cddfcdce17e48b73393ec78ad8ac42434809e0a`.

Raw nominal index-point errors remain within each provider and base year; only historical-scale-normalized errors pool sources. WAPE excludes no zero or near-zero months; sMAPE assigns zero error to exactly-zero actual/forecast pairs. Seasonal MASE uses input-history twelve-month differences only, with undefined short/zero denominators reported in JSON.

| Historical months supplied (stress only) | Selected normalized MAE | Naive normalized MAE |
| ---------------------------------------- | ----------------------: | -------------------: |
| 3                                        |                  0.1807 |               0.1394 |
| 6                                        |                  0.1775 |               0.1269 |
| 12                                       |                  0.1640 |               0.0853 |

The same observed final targets are reused with only 3/6/12 historical months supplied. This is a stress slice, not more independent real observations, and does not choose or qualify the frozen candidate.

Whole-US Census MRTS was inaccessible without an API key; FRED workaround terms disallowed ML use. These sources were excluded before reading audit observations. The wholly unseen UK ONS source substituted solely for access/licensing; no source was selected on model errors.

Original aggregate nominal turnover/value indices are observed real revenues normalized to each publisher's base year, not borrower bank receipts or monetary values. Raw index points cannot be pooled across provider bases. Whole-country clusters retain within-country sector and economic-shock dependence. Seven intended audit countries provide limited descriptive uncertainty; current revision vintages are not an unrevised historical backtest. Dates are provider-local, since older-country training observations may follow an audit date. No real expense, repayment, capacity or default labels are present.

The first v2 external audit was performed before inspecting its labels and is preserved as external-audit-v2-frozen.json/.md. This run is a regression reproduction of consumed labels: the pinned revenue recipe and selected candidate must match before case construction, local exact fitted equality is recorded, and reproduced overall/provider losses must match within 1e-9 absolute tolerance. Cross-platform same-recipe builds need not have identical learned bytes; this reports metric equality at stated precision, not pointwise identical predictions. Changing only net blend/expense/scoring does not make the revenue audit fresh again. No fitting/selection occurs here; a changed revenue recipe requires new reserved external targets.

Presentation-only clarification after measurement: the narrative identifies the original frozen cohort as consumed evidence. Numeric results, measured timestamp and recorded evaluator SHA256 still identify the original measurement; no fitting or scoring was rerun.
