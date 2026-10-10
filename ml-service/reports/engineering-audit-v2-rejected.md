# Reserved synthetic engineering audit

Measured 2026-10-10T20:17:01.772844+00:00 with frozen model `local-v4-a93ef54f76f4-gradient_boosting-public60`. This is a new **synthetic** cohort, not a real bank dataset. This is the rejected first v2 measurement. The current engineering command runs the separately reserved v3 cohort; it does not rerun these consumed seeds.

The unchanged generator uses reserved positions 1,000,000–1,000,179, producing **180 unseen generated businesses / 2,160 future months**. Their latent cohorts/expense processes are not supplied to the forecast. Actual future net-flow SHA256: `360da034d133f348c77006e40f25819d7e7f19e8ce3f067d1e78866790c39598`.

| Forecast                  | MAE (indices) | Macro history-normalized MAE | Absolute-net WAPE (%) |
| ------------------------- | ------------: | ---------------------------: | --------------------: |
| Frozen serving forecast   |       87.6637 |                       0.1244 |               34.0318 |
| Fixed synthetic reference |       89.9799 |                       0.1292 |               34.9310 |

Macro normalized MAE improvement: **3.6751%**; whole-business bootstrap descriptive 95% interval `[1.1423833013571523, 6.209734024008111]` percentage points. The comparator is the unchanged selected synthetic HGB/net forecast on the same request, not a newly optimized baseline.

Actual real-trained component mean effective weight: **49.69%**, range 25.00–60.00%. 127 businesses receive at least half real-trained contribution. Real candidate `adaptive_revenue_10`; expense policy `observed_cost_regression`.

Predetermined engineering acceptance: **FAIL**. Macro normalized error may worsen no more than 2%, pooled indexed error no more than 5%, and each predeclared cohort error no more than 15%; mean effective real weight must reach 50% and the revenue candidate must use a real-trained estimator. These tolerances mean no material regression in a finite generated sample. They do not claim an accuracy gain when the measured difference is negative. Checks: `{'macro_business_normalized_mae': True, 'pooled_mae_index': True, 'cohort_regressions': True, 'majority_actual_real_component': False, 'selected_uses_real_trained_estimator': True}`.

| Cohort             | Businesses | Serving normalized MAE | Fixed synthetic normalized MAE |
| ------------------ | ---------: | ---------------------: | -----------------------------: |
| cold_start         |         20 |                 0.1298 |                         0.1275 |
| declining          |         20 |                 0.0677 |                         0.0826 |
| growing            |         20 |                 0.0907 |                         0.1067 |
| negative_surplus   |         20 |                 0.0762 |                         0.0818 |
| pattern_break      |         20 |                 0.2290 |                         0.2002 |
| seasonal           |         20 |                 0.0723 |                         0.0823 |
| stable             |         20 |                 0.0593 |                         0.0634 |
| unseen_seasonality |         20 |                 0.1248 |                         0.1525 |
| volatile_growth    |         20 |                 0.2697 |                         0.2656 |

The actual scoring path produced 180 validated responses, 152 positive indexed principal recommendations and 28 zero-principal recommendations. Every adaptive schedule sums to its indexed principal. These checks do not establish realised affordability. Short-history slices and bootstrap details are in [the full JSON audit](engineering-audit-v2-rejected.json). WAPE retains zero and near-zero months and uses absolute actual net surplus in its denominator.

These reserved seeds are not used in fitting, validation or tuning. Reruns reproduce the same frozen model; after inspecting results this cohort is consumed for subsequent model revisions. Do not retune on this audit.

Every business, expense and future net-flow target in this report is synthetic. More real-trained forecast usage does not make expenses, capacity scores or repayment outcomes real-labeled. This is an engineering regression guard, not evidence of bank performance.

The 60%/25% policy is rejected because mean effective real contribution is 0.4969444444444444, below the unchanged 0.50 gate. Error guards passed; the majority-share failure remains a failure.
