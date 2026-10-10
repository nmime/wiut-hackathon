# Reserved synthetic engineering audit

Measured 2026-10-10T20:36:57.256643+00:00 with frozen model `local-v4-599a354d528f-gradient_boosting-public75`. This is a new **synthetic** cohort, not a real bank dataset. This is the rejected v4 measurement. Future engineering commands use separately reserved v5 seeds; v4 targets are consumed.

The unchanged generator uses reserved positions 3,000,000–3,000,899, producing **900 unseen generated businesses / 10,800 future months**. Their latent cohorts/expense processes are not supplied to the forecast. Actual future net-flow SHA256: `9fa3b75adc3c830c6d7bc5acc97ee5059bdf10c9b615703d6f940bb967054513`.

| Forecast                  | MAE (indices) | Macro history-normalized MAE | Absolute-net WAPE (%) |
| ------------------------- | ------------: | ---------------------------: | --------------------: |
| Frozen serving forecast   |       92.9967 |                       0.1249 |               31.9566 |
| Fixed synthetic reference |       97.8980 |                       0.1314 |               33.6408 |

Macro normalized MAE improvement: **4.8855%**; whole-business bootstrap descriptive 95% interval `[3.5091462381595817, 6.270568881271114]` percentage points. The comparator is the unchanged selected synthetic HGB/net forecast on the same request, not a newly optimized baseline.

Actual real-trained component mean effective weight: **60.56%**, range 25.00–75.00%. 640 businesses receive at least half real-trained contribution. Real candidate `adaptive_revenue_10`; expense policy `observed_cost_projection`.

Predetermined engineering acceptance: **FAIL**. Macro normalized error may worsen no more than 2%, pooled indexed error no more than 5%, and each predeclared cohort error no more than 15%; mean effective real weight must reach 50% and the revenue candidate must use a real-trained estimator. These tolerances mean no material regression in a finite generated sample. They do not claim an accuracy gain when the measured difference is negative. Checks: `{'macro_business_normalized_mae': True, 'pooled_mae_index': True, 'cohort_regressions': False, 'majority_actual_real_component': True, 'selected_uses_real_trained_estimator': True}`.

| Cohort             | Businesses | Serving normalized MAE | Fixed synthetic normalized MAE |
| ------------------ | ---------: | ---------------------: | -----------------------------: |
| cold_start         |        100 |                 0.1270 |                         0.1276 |
| declining          |        100 |                 0.0688 |                         0.0810 |
| growing            |        100 |                 0.0868 |                         0.1104 |
| negative_surplus   |        100 |                 0.0780 |                         0.0814 |
| pattern_break      |        100 |                 0.2203 |                         0.1905 |
| seasonal           |        100 |                 0.0712 |                         0.0830 |
| stable             |        100 |                 0.0644 |                         0.0691 |
| unseen_seasonality |        100 |                 0.1137 |                         0.1491 |
| volatile_growth    |        100 |                 0.2942 |                         0.2902 |

The actual scoring path produced 900 validated responses, 745 positive indexed principal recommendations and 155 zero-principal recommendations. Every adaptive schedule sums to its indexed principal. These checks do not establish realised affordability. Short-history slices and bootstrap details are in [the full JSON audit](engineering-audit-v4-rejected.json). WAPE retains zero and near-zero months and uses absolute actual net surplus in its denominator.

These reserved seeds are not used in fitting, validation or tuning. Reruns reproduce the same frozen model; after inspecting results this cohort is consumed for subsequent model revisions. Do not retune on this audit.

Every business, expense and future net-flow target in this report is synthetic. More real-trained forecast usage does not make expenses, capacity scores or repayment outcomes real-labeled. This is an engineering regression guard, not evidence of bank performance.

Exploratory sequential development: v2 positions 1,000,000–1,000,179 rejected the 60%/25% policy because mean real weight 0.4969444444444444 missed the unchanged 0.50 gate. V3 positions 2,000,000–2,000,899 rejected fixed50 because pattern-break normalized error worsened 20.727901853928323%, beyond the unchanged 15% cohort guard, despite overall normalized skill 4.382197570698798% and 0.50 mean weight. Both failures remain preserved in engineering-audit-v2-rejected.json/.md and engineering-audit-v3-rejected.json/.md. The next expense/serving policy is chosen only on original training/development cases, with real estimators/candidate, generator, synthetic comparator and audit thresholds unchanged. V4 positions 3,000,000–3,000,899 were reserved before their target construction. Multiple audit-driven revisions make the development path exploratory; a later pass is not guaranteed superiority or an unconditional single-shot confidence claim.

V4 remains rejected because its cohort-regression guard fails. Other acceptance checks passed; they do not erase this slice failure. The sequential development path and all earlier failures remain disclosed.
