# Portable-build consumed V5 engineering regression

Measured 2026-10-10T21:11:30.984300+00:00 with frozen model `local-v4-bf33fb45ddc3-gradient_boosting-public65`. This is a **same-recipe portable-build regression on consumed V5 targets**. Fitted estimators and actual losses may differ from the original Mac model; this build independently checks the unchanged engineering gates against the same stored targets. The first result remains in [the original V5 audit](engineering-audit-v5-frozen.json). This run adds no independent evidence and does not claim exact loss reproduction. Reproduce with `uv run python -m capacity_ml.evaluate_engineering`.

The unchanged generator uses reserved positions 4,000,000–4,000,899, producing **900 originally unseen generated businesses / 10,800 future months**. Their latent cohorts/expense processes are not supplied to the forecast. Actual future net-flow SHA256: `67ba3d38448902e7c2b26e02458038bc2b1707e17081da05dedcad463ad03178`.

| Forecast                  | MAE (indices) | Macro history-normalized MAE | Absolute-net WAPE (%) |
| ------------------------- | ------------: | ---------------------------: | --------------------: |
| Frozen serving forecast   |       89.1564 |                       0.1252 |               31.6362 |
| Fixed synthetic reference |       95.1815 |                       0.1324 |               33.7741 |

Macro normalized MAE improvement: **5.4781%**; whole-business bootstrap descriptive 95% interval `[4.399499435324139, 6.603730756019654]` percentage points. The comparator is the unchanged selected synthetic HGB/net forecast on the same request, not a newly optimized baseline.

Actual real-trained component mean effective weight: **53.18%**, range 25.00–65.00%. 634 businesses receive at least half real-trained contribution. Real candidate `adaptive_revenue_10`; expense policy `observed_cost_projection`.

Predetermined engineering acceptance: **PASS**. Macro normalized error may worsen no more than 2%, pooled indexed error no more than 5%, and each predeclared cohort error no more than 15%; mean effective real weight must reach 50% and the revenue candidate must use a real-trained estimator. These tolerances mean no material regression in a finite generated sample. They do not claim an accuracy gain when the measured difference is negative. Checks: `{'macro_business_normalized_mae': True, 'pooled_mae_index': True, 'cohort_regressions': True, 'majority_actual_real_component': True, 'selected_uses_real_trained_estimator': True}`.

| Cohort             | Businesses | Serving normalized MAE | Fixed synthetic normalized MAE |
| ------------------ | ---------: | ---------------------: | -----------------------------: |
| cold_start         |        100 |                 0.1214 |                         0.1213 |
| declining          |        100 |                 0.0717 |                         0.0846 |
| growing            |        100 |                 0.0961 |                         0.1189 |
| negative_surplus   |        100 |                 0.0813 |                         0.0874 |
| pattern_break      |        100 |                 0.2097 |                         0.1889 |
| seasonal           |        100 |                 0.0686 |                         0.0812 |
| stable             |        100 |                 0.0642 |                         0.0691 |
| unseen_seasonality |        100 |                 0.1131 |                         0.1404 |
| volatile_growth    |        100 |                 0.3005 |                         0.3001 |

The actual scoring path produced 900 validated responses, 757 positive indexed principal recommendations and 143 zero-principal recommendations. Every adaptive schedule sums to its indexed principal. These checks do not establish realised affordability. Short-history slices and bootstrap details are in [the full JSON audit](engineering-metrics.json). WAPE retains zero and near-zero months and uses absolute actual net surplus in its denominator.

The first Mac V5 result is preserved as engineering-audit-v5-frozen.json/.md. Original stored targets recover its raw ID/float64 hashes exactly; every native regenerated target is checked within 1e-9 absolute index precision before scoring, with native hash/deviation reported separately. Metrics use the stored original targets. Exact source, policies, protocol, candidate addendum and component recipes are required. Same-local-fitted reruns require strict loss reproduction. A differing-fitted portable same-recipe build instead must independently pass every unchanged engineering gate and exact identity/count/scoring invariants; its actual losses/deltas and any strict loss-reproduction FAIL remain visible. This is consumed-cohort regression, never new independent evidence or a byte-identical predictor. A revised serving pipeline requires new reserved targets and cannot retune on V5.

Every business, expense and future net-flow target in this report is synthetic. More real-trained forecast usage does not make expenses, capacity scores or repayment outcomes real-labeled. This is an engineering regression guard, not evidence of bank performance.

Fourth exploratory sequential cycle: v2 rejected the 60%/25% policy because mean real weight 0.4969444444444444 missed the unchanged 0.50 gate; v3 and v4 both failed the unchanged 15% cohort-regression gate despite other aggregate/weight checks passing. Preserve all three outcomes as engineering-audit-v2-rejected.json/.md, engineering-audit-v3-rejected.json/.md and engineering-audit-v4-rejected.json/.md. History-only net reliability routers were explored exclusively on original training/development cases using already-observed historical 12-month target windows and finite margins 0/5/10/15; they were not selected for serving. The existing median_share12 observed-cost projection and guard65/25/25 policy are selected from the original finite grid with a tighter 10% development cohort buffer and accurately summed 55% development mean-share cushion. The independent audit remains 15% and mean50; reserved target labels supply no corrective coefficients. Real fitting recipe/candidate, generator, synthetic comparator recipe and audit thresholds remain frozen during policy reselection; portable fitted-byte differences are disclosed. V5 positions 4,000,000–4,000,899 were reserved before their target construction. Multiple failure-driven revisions make the development path exploratory; a later pass is not guaranteed superiority or an unconditional single-shot confidence claim.

Consumed-cohort regression qualification: **PASS**, mode `same_recipe_portable_build_consumed_v5_regression`. Strict metric reproduction against the first Mac result: **FAIL**. Source, policy, recipes and protocol are checked before target reconstruction. Strict normalized MAE tolerance is `1e-09`; indexed MAE tolerance `1e-06`; percentages and descriptive interval bounds `1e-06`. A same-local fitted model must meet these precisions. A differing-fitted portable build instead must independently pass all five unchanged gates, and retain any strict reproduction failure and every actual metric delta. IDs, original target hashes, slice identities, counts, actual shares and scoring invariants remain exact apart from declared summation roundoff. Continuity and measured deltas are in [the full JSON report](engineering-metrics.json).

Every one of **10,800 original target points** agrees with the native regenerated value within `1e-09` index units, with zero relative tolerance; maximum difference `9.094947017729282e-13`. Errors use the frozen original stored targets. Original raw float64 target SHA256 `67ba3d38448902e7c2b26e02458038bc2b1707e17081da05dedcad463ad03178`; native regenerated SHA256 `14135c4dccf0041abb8e30224eb39c01b24b6af4b7f9f6ef5341568ebd76d31a`; exact raw-hash match `False`. The manifest recovers the first measurement's original ID/target hashes exactly; native platform differences are disclosed rather than silently dropped.

Presentation-only clarification after measurement: frozen recipes are distinguished from portable fitted-byte differences. Numeric results, measured timestamp and recorded evaluator SHA256 still identify the original measurement; no fitting or scoring was rerun.
