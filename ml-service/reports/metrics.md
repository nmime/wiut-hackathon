# Measured synthetic regression evaluation

Measured 2026-10-10T19:30:43.452541+00:00. Model `local-v3-90057d5d69d7-gradient_boosting-public10`.

All results below were produced by `uv run python -m capacity_ml.evaluate` on generated future transactions. They are synthetic engineering measurements, not evidence of bank performance or default prediction.

This fixed synthetic test cohort was reported before the model upgrade and is now a **legacy regression benchmark**, not a fresh confirmatory holdout. Its labels remain excluded from fitting and validation selection. The new [international evaluation](international-metrics.md) measures real revenue against separately reserved final-period observations.

Public Uzbekistan SIAT 2020–2022 retail aggregates calibrate half the calendar component for four retail-like synthetic cohorts; later aggregate years are excluded from generator calibration. Every borrower transaction, expense and future net-flow target remains synthetic. An additional real-revenue component is trained directly from licensed aggregates and transferred only if synthetic validation MAE improves; its separate report measures actual public revenue forecasts, never borrower capacity.

Selection used 180 training businesses (complete/partial rolling origins) and 60 separate validation businesses. The selected candidate is **gradient_boosting** by validation MAE. The held-out 120 test businesses are disjoint from both sets and each contributes 12 future actual months. Test metrics did not change model selection, buffers, score weights or schedule policy.

| Candidate         | Validation MAE (index) | Test MAE (index) | Test MAPE (%) | Test WAPE (%) |
| ----------------- | ---------------------: | ---------------: | ------------: | ------------: |
| seasonal_naive    |                 132.86 |           100.43 |         62.53 |         38.08 |
| gradient_boosting |                 106.09 |            88.23 |         52.66 |         33.46 |
| blend_50          |                 115.04 |            90.28 |         53.60 |         34.24 |

The real-revenue model minus the selected expense projection (`observed_cost_regression`) is compared with the chosen synthetic net model at fixed weights 0/0.1/0.25/0.5/1. Expenses use either synthetic training or the borrower's observed cost relationship; no public cost labels are supplied. Validation selects public weight **0.1** and serving mode `real_revenue_observed_costs_blend`, requiring real validation skill, better pooled net MAE and a macro normalized-error guard. This decision precedes the regression results below; zero rejects unsuitable transfer.

| Public component weight | Synthetic validation MAE (index) | Held-out MAE (index) |
| ----------------------- | -------------------------------: | -------------------: |
| 0.0                     |                           106.09 |                88.23 |
| 0.1                     |                           105.65 |                87.23 |
| 0.25                    |                           105.77 |                86.26 |
| 0.5                     |                           108.47 |                86.90 |
| 1.0                     |                           120.80 |                94.83 |

MAPE excludes 0 months with absolute actual surplus below 1 index; negative actuals use an absolute denominator. Near-zero/negative net flow makes this percentage difficult to interpret. MAE is the selection metric; WAPE is also shown. No forecast intervals or calibrated confidence probabilities are claimed.

The selected model's separate partial-assessment-month test MAE is **90.78 indices**. Incomplete current-month events are excluded while the target remains the next 12 calendar months after assessment.

Positive indexed loans were recommended for **96/120** test businesses; zero-loan cases are excluded from the following repayment metrics to avoid a trivial zero-payment success rate. Adaptive capacity coverage is **96.88%** of those future business-months; coverage for the conservative 20th-percentile equal-installment reference is **96.79%**.

For the same principal, 12-month term and explicit 0% APR, adaptive schedules produce **36 overload months** versus **38** for equal installments (the zero-interest annuity). **5.21%** of eligible businesses improve, **91.67%** tie and **3.12%** worsen. Overload means payment exceeds actual net surplus; zero payments in negative months count too. Forecast-based caps cannot guarantee future affordability.

The measured overload reduction (equal minus adaptive) is **2 months** in this test; a negative value means adaptive is worse. It is not a consistent advantage for every business and must not be marketed as proven repayment improvement. Model and buffer settings remain fixed rather than being retuned on these test outcomes.

Weak/strong-month precision against future realised quartiles is **44.17% / 37.22%**. Many forecast labels miss the realised quartiles. The evaluator never reads hidden generator seasonal parameters as labels.

| Cohort             | Businesses | MAE (index) | Loans | Mean confidence | Adaptive coverage (%) | Adaptive overloads | Equal overloads |
| ------------------ | ---------: | ----------: | ----: | --------------: | --------------------: | -----------------: | --------------: |
| cold_start         |         13 |       67.72 |     2 |           0.096 |                100.00 |                  0 |               0 |
| declining          |         13 |       28.23 |    13 |           0.703 |                 99.36 |                  1 |               2 |
| growing            |         14 |      102.95 |    14 |           0.718 |                100.00 |                  0 |               0 |
| negative_surplus   |         13 |       53.51 |     0 |           0.668 |                   n/a |                  0 |               0 |
| pattern_break      |         13 |       84.93 |    13 |           0.620 |                 84.62 |                 24 |              24 |
| seasonal           |         14 |       35.00 |    14 |           0.714 |                100.00 |                  0 |               0 |
| stable             |         14 |       48.38 |    14 |           0.855 |                100.00 |                  0 |               0 |
| unseen_seasonality |         13 |       76.83 |    13 |           0.503 |                 98.72 |                  2 |               3 |
| volatile_growth    |         13 |      293.37 |    13 |           0.516 |                 94.23 |                  9 |               9 |

Known failures include short history, noisy high growth, unseen seasonal shapes and abrupt pattern breaks. The flags detect some observed changes; no flag can identify a future shock. Confidence is an evidence heuristic and must not be presented as calibrated certainty. Results for each difficult cohort are shown even where the model or adaptive schedule disappoints.

On `macOS-26.5.1-arm64-arm-64bit` (`arm64`, 12 logical CPUs), 120 sequential warm measurements gave inference median/P95 **7.69/13.85 ms**, and local `/score` TestClient median/P95 **8.95/20.10 ms** including JSON validation, response serialization and audit fsync. HTTP counts: `{'200': 120}`. These exclude real network latency, concurrent load, training and startup; reruns change timings.

A separate five-request stress sample with the allowed maximum **20,000 synthetic transaction events** (2152323 body bytes) measured median/P95 **53.24/112.48 ms**. Status counts: `{'200': 5}`. The generated events are repeated for this latency-only check; this is not an additional accuracy sample.

Local inference calls no external API and incurs no per-request provider fee. CPU, memory, storage, operational support and retraining still cost money; no monetary cost estimate was measured. The README lists deployment and validation limitations.

[Machine-readable measured values](metrics.json)
