# Reserved synthetic engineering audit

Measured 2026-10-10T20:52:12.478707+00:00 with frozen model `local-v4-bf33fb45ddc3-gradient_boosting-public65`. This is a new **synthetic** cohort, not a real bank dataset. This preserves the first V5 measurement; subsequent `uv run python -m capacity_ml.evaluate_engineering` runs reproduce consumed labels under continuity checks.

The unchanged generator uses reserved positions 4,000,000–4,000,899, producing **900 unseen generated businesses / 10,800 future months**. Their latent cohorts/expense processes are not supplied to the forecast. Actual future net-flow SHA256: `67ba3d38448902e7c2b26e02458038bc2b1707e17081da05dedcad463ad03178`.

| Forecast                  | MAE (indices) | Macro history-normalized MAE | Absolute-net WAPE (%) |
| ------------------------- | ------------: | ---------------------------: | --------------------: |
| Frozen serving forecast   |       89.1476 |                       0.1252 |               31.6331 |
| Fixed synthetic reference |       95.1815 |                       0.1324 |               33.7741 |

Macro normalized MAE improvement: **5.4781%**; whole-business bootstrap descriptive 95% interval `[4.408429521099184, 6.597061148891429]` percentage points. The comparator is the unchanged selected synthetic HGB/net forecast on the same request, not a newly optimized baseline.

Actual real-trained component mean effective weight: **53.18%**, range 25.00–65.00%. 634 businesses receive at least half real-trained contribution. Real candidate `adaptive_revenue_10`; expense policy `observed_cost_projection`.

Predetermined engineering acceptance: **PASS**. Macro normalized error may worsen no more than 2%, pooled indexed error no more than 5%, and each predeclared cohort error no more than 15%; mean effective real weight must reach 50% and the revenue candidate must use a real-trained estimator. These tolerances mean no material regression in a finite generated sample. They do not claim an accuracy gain when the measured difference is negative. Checks: `{'macro_business_normalized_mae': True, 'pooled_mae_index': True, 'cohort_regressions': True, 'majority_actual_real_component': True, 'selected_uses_real_trained_estimator': True}`.

| Cohort             | Businesses | Serving normalized MAE | Fixed synthetic normalized MAE |
| ------------------ | ---------: | ---------------------: | -----------------------------: |
| cold_start         |        100 |                 0.1214 |                         0.1213 |
| declining          |        100 |                 0.0717 |                         0.0846 |
| growing            |        100 |                 0.0960 |                         0.1189 |
| negative_surplus   |        100 |                 0.0813 |                         0.0874 |
| pattern_break      |        100 |                 0.2097 |                         0.1889 |
| seasonal           |        100 |                 0.0686 |                         0.0812 |
| stable             |        100 |                 0.0643 |                         0.0691 |
| unseen_seasonality |        100 |                 0.1131 |                         0.1404 |
| volatile_growth    |        100 |                 0.3005 |                         0.3001 |

The actual scoring path produced 900 validated responses, 757 positive indexed principal recommendations and 143 zero-principal recommendations. Every adaptive schedule sums to its indexed principal. These checks do not establish realised affordability. Short-history slices and bootstrap details are in [the full JSON audit](engineering-audit-v5-frozen.json). WAPE retains zero and near-zero months and uses absolute actual net surplus in its denominator.

These reserved seeds are not used in fitting, validation or tuning. Reruns reproduce the same frozen model; after inspecting results this cohort is consumed for subsequent model revisions. Do not retune on this audit.

Every business, expense and future net-flow target in this report is synthetic. More real-trained forecast usage does not make expenses, capacity scores or repayment outcomes real-labeled. This is an engineering regression guard, not evidence of bank performance.

Fourth exploratory sequential cycle: v2 rejected the 60%/25% policy because mean real weight 0.4969444444444444 missed the unchanged 0.50 gate; v3 and v4 both failed the unchanged 15% cohort-regression gate despite other aggregate/weight checks passing. Preserve all three outcomes as engineering-audit-v2-rejected.json/.md, engineering-audit-v3-rejected.json/.md and engineering-audit-v4-rejected.json/.md. History-only net reliability routers were explored exclusively on original training/development cases using already-observed historical 12-month target windows and finite margins 0/5/10/15; they were not selected for serving. The existing median_share12 observed-cost projection and guard65/25/25 policy are selected from the original finite grid with a tighter 10% development cohort buffer and accurately summed 55% development mean-share cushion. The independent audit remains 15% and mean50; reserved target labels supply no corrective coefficients. Real estimators/candidate, generator, synthetic comparator and audit thresholds remain frozen. V5 positions 4,000,000–4,000,899 were reserved before their target construction. Multiple failure-driven revisions make the development path exploratory; a later pass is not guaranteed superiority or an unconditional single-shot confidence claim.
