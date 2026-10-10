# Reserved synthetic engineering audit

Measured 2026-10-10T20:27:01.992051+00:00 with frozen model `local-v4-1d77bfaf49a0-gradient_boosting-public50`. This is a new **synthetic** cohort, not a real bank dataset. This is the rejected first v3 measurement. The current engineering command moves to separately reserved v4 seeds; these v3 seeds are consumed.

The unchanged generator uses reserved positions 2,000,000–2,000,899, producing **900 unseen generated businesses / 10,800 future months**. Their latent cohorts/expense processes are not supplied to the forecast. Actual future net-flow SHA256: `1f4dbb35f3b4ff3c5f7fc483f390b1a979981be7088d1d27e82f197aaaea3691`.

| Forecast                  | MAE (indices) | Macro history-normalized MAE | Absolute-net WAPE (%) |
| ------------------------- | ------------: | ---------------------------: | --------------------: |
| Frozen serving forecast   |       92.7495 |                       0.1240 |               32.6271 |
| Fixed synthetic reference |       96.8951 |                       0.1297 |               34.0854 |

Macro normalized MAE improvement: **4.3822%**; whole-business bootstrap descriptive 95% interval `[3.048158756313879, 5.784607143081776]` percentage points. The comparator is the unchanged selected synthetic HGB/net forecast on the same request, not a newly optimized baseline.

Actual real-trained component mean effective weight: **50.00%**, range 50.00–50.00%. 900 businesses receive at least half real-trained contribution. Real candidate `adaptive_revenue_10`; expense policy `observed_cost_regression`.

Predetermined engineering acceptance: **FAIL**. Macro normalized error may worsen no more than 2%, pooled indexed error no more than 5%, and each predeclared cohort error no more than 15%; mean effective real weight must reach 50% and the revenue candidate must use a real-trained estimator. These tolerances mean no material regression in a finite generated sample. They do not claim an accuracy gain when the measured difference is negative. Checks: `{'macro_business_normalized_mae': True, 'pooled_mae_index': True, 'cohort_regressions': False, 'majority_actual_real_component': True, 'selected_uses_real_trained_estimator': True}`.

| Cohort             | Businesses | Serving normalized MAE | Fixed synthetic normalized MAE |
| ------------------ | ---------: | ---------------------: | -----------------------------: |
| cold_start         |        100 |                 0.1310 |                         0.1234 |
| declining          |        100 |                 0.0667 |                         0.0782 |
| growing            |        100 |                 0.0949 |                         0.1134 |
| negative_surplus   |        100 |                 0.0839 |                         0.0888 |
| pattern_break      |        100 |                 0.2103 |                         0.1742 |
| seasonal           |        100 |                 0.0697 |                         0.0829 |
| stable             |        100 |                 0.0654 |                         0.0691 |
| unseen_seasonality |        100 |                 0.0997 |                         0.1386 |
| volatile_growth    |        100 |                 0.2945 |                         0.2986 |

The actual scoring path produced 900 validated responses, 754 positive indexed principal recommendations and 146 zero-principal recommendations. Every adaptive schedule sums to its indexed principal. These checks do not establish realised affordability. Short-history slices and bootstrap details are in [the full JSON audit](engineering-audit-v3-rejected.json). WAPE retains zero and near-zero months and uses absolute actual net surplus in its denominator.

These reserved seeds are not used in fitting, validation or tuning. Reruns reproduce the same frozen model; after inspecting results this cohort is consumed for subsequent model revisions. Do not retune on this audit.

Every business, expense and future net-flow target in this report is synthetic. More real-trained forecast usage does not make expenses, capacity scores or repayment outcomes real-labeled. This is an engineering regression guard, not evidence of bank performance.

The earlier v2 positions 1,000,000–1,000,179 are consumed and their 60%/25% policy is rejected: mean effective real weight 0.4969444444444444 missed the unchanged 0.50 gate, despite error guards passing. Preserve that outcome in engineering-audit-v2-rejected.json/.md. The revised serving policy is chosen solely from original development candidates constrained to at least half real contribution on every active history. This v3 range was reserved before target construction; no threshold is relaxed.

This v3 policy is rejected: pattern-break normalized MAE worsened 20.727901853928323%, beyond the unchanged 15% maximum. Overall normalized MAE improved 4.382197570698798% and the actual mean real weight was 0.50; those passes do not erase the cohort failure. All 900 cases and all nine cohorts remain in the report.
