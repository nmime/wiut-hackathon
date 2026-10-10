# Measured synthetic evaluation

Measured 2026-10-10T18:35:58.229193+00:00. Model `synthetic-v1-9a0379ca910d-gradient_boosting`.

All results below were produced by `uv run python -m capacity_ml.evaluate` on generated future transactions. They are synthetic engineering measurements, not evidence of bank performance or default prediction.

Public Uzbekistan SIAT 2020–2022 retail aggregates calibrate half the calendar component for four retail-like synthetic cohorts; test/validation aggregate years are excluded from calibration. Every business transaction, expense and future net-flow target remains synthetic. The separate public-data report measures actual aggregate revenue forecasts only.

Selection used 180 training businesses (complete/partial rolling origins) and 60 separate validation businesses. The selected candidate is **gradient_boosting** by validation MAE. The held-out 120 test businesses are disjoint from both sets and each contributes 12 future actual months. Test metrics did not change model selection, buffers, score weights or schedule policy.

| Candidate         | Validation MAE (index) | Test MAE (index) | Test MAPE (%) | Test WAPE (%) |
| ----------------- | ---------------------: | ---------------: | ------------: | ------------: |
| seasonal_naive    |                 132.86 |           100.43 |         62.53 |         38.08 |
| gradient_boosting |                 106.09 |            88.23 |         52.66 |         33.46 |
| blend_50          |                 115.04 |            90.28 |         53.60 |         34.24 |

MAPE excludes 0 months with absolute actual surplus below 1 index; negative actuals use an absolute denominator. Near-zero/negative net flow makes this percentage difficult to interpret. MAE is the selection metric; WAPE is also shown. No forecast intervals or calibrated confidence probabilities are claimed.

The selected model's separate partial-assessment-month test MAE is **91.72 indices**. Incomplete current-month events are excluded while the target remains the next 12 calendar months after assessment.

Positive indexed loans were recommended for **96/120** test businesses; zero-loan cases are excluded from the following repayment metrics to avoid a trivial zero-payment success rate. Adaptive capacity coverage is **96.79%** of those future business-months; coverage for the conservative 20th-percentile equal-installment reference is **96.44%**.

For the same principal, 12-month term and explicit 0% APR, adaptive schedules produce **37 overload months** versus **38** for equal installments (the zero-interest annuity). **5.21%** of eligible businesses improve, **91.67%** tie and **3.12%** worsen. Overload means payment exceeds actual net surplus; zero payments in negative months count too. Forecast-based caps cannot guarantee future affordability.

The measured aggregate adaptive benefit is only **1 fewer overload months** in this test. It is not a consistent advantage for every business and must not be marketed as proven repayment improvement. Model and buffer settings remain fixed rather than being retuned on these test outcomes.

Weak/strong-month precision against future realised quartiles is **43.02% / 36.49%**. Many forecast labels miss the realised quartiles. The evaluator never reads hidden generator seasonal parameters as labels.

| Cohort             | Businesses | MAE (index) | Loans | Mean confidence | Adaptive coverage (%) | Adaptive overloads | Equal overloads |
| ------------------ | ---------: | ----------: | ----: | --------------: | --------------------: | -----------------: | --------------: |
| cold_start         |         13 |       67.48 |     2 |           0.096 |                100.00 |                  0 |               0 |
| declining          |         13 |       28.39 |    13 |           0.703 |                 99.36 |                  1 |               2 |
| growing            |         14 |      107.45 |    14 |           0.718 |                100.00 |                  0 |               0 |
| negative_surplus   |         13 |       54.54 |     0 |           0.668 |                   n/a |                  0 |               0 |
| pattern_break      |         13 |       82.09 |    13 |           0.620 |                 83.97 |                 25 |              24 |
| seasonal           |         14 |       36.13 |    14 |           0.714 |                100.00 |                  0 |               0 |
| stable             |         14 |       47.93 |    14 |           0.855 |                100.00 |                  0 |               0 |
| unseen_seasonality |         13 |       81.59 |    13 |           0.503 |                 98.72 |                  2 |               3 |
| volatile_growth    |         13 |      294.07 |    13 |           0.516 |                 94.23 |                  9 |               9 |

Known failures include short history, noisy high growth, unseen seasonal shapes and abrupt pattern breaks. The flags detect some observed changes; no flag can identify a future shock. Confidence is an evidence heuristic and must not be presented as calibrated certainty. Results for each difficult cohort are shown even where the model or adaptive schedule disappoints.

On `macOS-26.5.1-arm64-arm-64bit` (`arm64`, 12 logical CPUs), 120 sequential warm measurements gave inference median/P95 **1.78/2.26 ms**, and local `/score` TestClient median/P95 **5.54/7.51 ms** including JSON validation, response serialization and audit fsync. HTTP counts: `{'200': 120}`. These exclude real network latency, concurrent load, training and startup; reruns change timings.

A separate five-request stress sample with the allowed maximum **20,000 synthetic transaction events** (2152323 body bytes) measured median/P95 **48.55/103.72 ms**. Status counts: `{'200': 5}`. The generated events are repeated for this latency-only check; this is not an additional accuracy sample.

Local inference calls no external API and incurs no per-request provider fee. CPU, memory, storage, operational support and retraining still cost money; no monetary cost estimate was measured. The README lists deployment and validation limitations.

[Machine-readable measured values](metrics.json)
