# Measured synthetic regression evaluation

Measured 2026-10-10T20:54:52.735822+00:00. Model `local-v4-bf33fb45ddc3-gradient_boosting-public65`.

All results below were produced by `uv run python -m capacity_ml.evaluate` on generated future transactions. They are synthetic engineering measurements, not evidence of bank performance or default prediction.

This fixed synthetic test cohort was reported before the model upgrade and is now a **legacy regression benchmark**, not a fresh confirmatory holdout. Its labels remain excluded from fitting and validation selection. The [external-provider audit](external-metrics.md) measures real revenue against a separately reserved provider; the previously reported international evaluation is also a legacy regression.

Public Uzbekistan SIAT 2020–2022 retail aggregates calibrate half the calendar component for four retail-like synthetic cohorts; later aggregate years are excluded from generator calibration. Every borrower transaction, expense and future net-flow target remains synthetic. An additional real-revenue component is trained directly from licensed aggregates and transferred only if synthetic validation MAE improves; its separate report measures actual public revenue forecasts, never borrower capacity.

Selection used 180 training businesses (complete/partial rolling origins) and 60 separate validation businesses. The selected synthetic reference is **gradient_boosting** by validation MAE; the final serving policy additionally blends its net forecast with the qualified real-revenue/expense component. The held-out 120 test businesses are disjoint from both sets and each contributes 12 future actual months. Test metrics did not change model selection, buffers, score weights or schedule policy.

| Candidate         | Validation MAE (index) | Test MAE (index) | Test MAPE (%) | Test WAPE (%) |
| ----------------- | ---------------------: | ---------------: | ------------: | ------------: |
| seasonal_naive    |                 132.86 |           100.43 |         62.53 |         38.08 |
| gradient_boosting |                 106.09 |            88.23 |         52.66 |         33.46 |
| blend_50          |                 115.04 |            90.28 |         53.60 |         34.24 |

The actual serving policy is `guard_0.65_0.25_0.25`, using real-revenue candidate `adaptive_revenue_10` and expense policy `observed_cost_projection`. Its configured real-component share is **65%**. The synthetic share is the remaining fraction. Expenses use either synthetic training or the borrower's observed cost relationship; no public expense, repayment or default labels are supplied.

Real contribution becomes **25%** with fewer than 12 observed calendar months, or **25%** when the positive prior-three-month inflow mean gives a recent-three/prior-three ratio outside [0.65, 1.55]. Routing uses only observed history, with no future, provider or cohort labels. Histories with no activity in the latest 12 months receive a zero forecast without trained inference.

The selected observed-cost projection multiplies predicted revenue by the median observed outflow/inflow ratio over the latest 12 calendar months with positive inflow. If that window has no positive inflow, it uses mean observed outflow instead. Historical fixed costs are included implicitly in the ratio; proportional projection can overstate costs when revenue rises. This is an observation-based assumption, not a public-trained expense model.

The policy's actual real contribution across development validation requests averaged **55.00%**, ranging from **25% to 65%**; counts by effective weight: `{'0.25': 15, '0.65': 45}`. This is a forecast-component contribution, not an accuracy percentage. The revenue ensemble itself contains real-trained residual estimators, statistical baselines and adaptation to observed borrower history.

The bounded transfer grid contains 38 policies: eight fixed weights (0/0.1/0.25/0.5/0.6/0.65/0.75/1), plus 30 observed-history guards from five base shares (0.5/0.6/0.65/0.75/1), three regime shares (0/0.25/0.5), and two short-history shares (0.25/0.5). The original expense regression is now compared with three regularized observed regressions, 18 seasonal-outflow blends and two observed median-share projections: 24 observed-cost policies, plus the original synthetic expense benchmark. Every combination is measured only on original development validation; the externally audited real candidate remains fixed. Real provider-balanced normalized MAE must improve seasonal naive by at least 5%, no real provider may regress more than 2%, pooled net MAE must improve, macro normalized net MAE may regress at most 2%, and no validation cohort may regress more than 15%. Selection additionally requires a tighter 10% development cohort buffer, while the final audit retains its original 15% cohort tolerance. Development mean real contribution must be at least 55%, using math.fsum without threshold rounding, providing a cushion above the unchanged audit mean50 requirement. Revenue estimators never fit synthetic targets; legacy outcomes below did not select the policy.

The first reserved engineering audit rejected the original 60%/25% guarded policy solely because its mean real contribution was below the frozen 50% requirement. A second separately reserved audit rejected the subsequent fixed50 policy on a cohort error guard. A third reserved audit rejected the subsequent median-share12 guard75/25/25 policy on a cohort guard. All three failed reports remain preserved. This fourth exploratory cycle selects the simple original-grid policy with a tighter 10% development cohort buffer, without reading consumed audit target labels or cohort errors. Two 7,296-combination local net-history grids found no majority-qualified policy (maximum share 41.25%). A 29,184-combination latest-origin variant qualified some policies but was rejected for complexity, missing supported local evidence in 31 of 60 histories and slightly worse pooled error. The externally audited real candidate and training recipe remain fixed. A fourth separately reserved engineering audit evaluates this policy under unchanged acceptance thresholds. Sequential development after aggregate audit rejection is exploratory; each consumed audit remains consumed.

| Actual policy           | Validation MAE (index) | Validation macro normalized MAE | Legacy regression MAE (index) |
| ----------------------- | ---------------------: | ------------------------------: | ----------------------------: |
| Synthetic reference     |                 106.09 |                        0.122606 |                         88.23 |
| Selected serving policy |                 100.64 |                        0.116933 |                         84.23 |

The following fixed-weight comparisons are supporting regression measurements. Each row applies its weight uniformly; the selected guarded policy requires the separate actual-policy row above and differs from the fixed row at its configured base share.

| Fixed public component weight | Synthetic validation MAE (index) | Legacy regression MAE (index) |
| ----------------------------- | -------------------------------: | ----------------------------: |
| 0.0                           |                           106.09 |                         88.23 |
| 0.1                           |                           104.55 |                         87.04 |
| 0.25                          |                           102.85 |                         85.57 |
| 0.5                           |                           101.41 |                         84.24 |
| 0.6                           |                           101.20 |                         84.16 |
| 0.65                          |                           101.23 |                         84.17 |
| 0.75                          |                           101.50 |                         84.34 |
| 1.0                           |                           103.23 |                         85.56 |

MAPE excludes 0 months with absolute actual surplus below 1 index; negative actuals use an absolute denominator. Near-zero/negative net flow makes this percentage difficult to interpret. MAE is the selection metric; WAPE is also shown. No forecast intervals or calibrated confidence probabilities are claimed.

The selected model's separate partial-assessment-month test MAE is **87.67 indices**. Incomplete current-month events are excluded while the target remains the next 12 calendar months after assessment.

Positive indexed loans were recommended for **96/120** test businesses; zero-loan cases are excluded from the following repayment metrics to avoid a trivial zero-payment success rate. Adaptive capacity coverage is **96.44%** of those future business-months; coverage for the conservative 20th-percentile equal-installment reference is **96.53%**.

For the same principal, 12-month term and explicit 0% APR, adaptive schedules produce **41 overload months** versus **41** for equal installments (the zero-interest annuity). **5.21%** of eligible businesses improve, **90.62%** tie and **4.17%** worsen. Overload means payment exceeds actual net surplus; zero payments in negative months count too. Forecast-based caps cannot guarantee future affordability.

The measured overload reduction (equal minus adaptive) is **0 months** in this test; a negative value means adaptive is worse. It is not a consistent advantage for every business and must not be marketed as proven repayment improvement. Model and buffer settings remain fixed rather than being retuned on these test outcomes.

Weak/strong-month precision against future realised quartiles is **48.06% / 40.83%**. Many forecast labels miss the realised quartiles. The evaluator never reads hidden generator seasonal parameters as labels.

| Cohort             | Businesses | MAE (index) | Loans | Mean confidence | Adaptive coverage (%) | Adaptive overloads | Equal overloads |
| ------------------ | ---------: | ----------: | ----: | --------------: | --------------------: | -----------------: | --------------: |
| cold_start         |         13 |       67.18 |     2 |           0.096 |                100.00 |                  0 |               0 |
| declining          |         13 |       26.15 |    13 |           0.703 |                 99.36 |                  1 |               2 |
| growing            |         14 |       89.78 |    14 |           0.718 |                100.00 |                  0 |               0 |
| negative_surplus   |         13 |       50.86 |     0 |           0.668 |                   n/a |                  0 |               0 |
| pattern_break      |         13 |       92.03 |    13 |           0.620 |                 81.41 |                 29 |              26 |
| seasonal           |         14 |       33.01 |    14 |           0.714 |                100.00 |                  0 |               1 |
| stable             |         14 |       49.06 |    14 |           0.855 |                100.00 |                  0 |               0 |
| unseen_seasonality |         13 |       61.60 |    13 |           0.503 |                 98.72 |                  2 |               3 |
| volatile_growth    |         13 |      294.66 |    13 |           0.516 |                 94.23 |                  9 |               9 |

Known failures include short history, noisy high growth, unseen seasonal shapes and abrupt pattern breaks. The flags detect some observed changes; no flag can identify a future shock. Confidence is an evidence heuristic and must not be presented as calibrated certainty. Results for each difficult cohort are shown even where the model or adaptive schedule disappoints.

On `macOS-26.5.1-arm64-arm-64bit` (`arm64`, 12 logical CPUs), 120 sequential warm measurements gave inference median/P95 **8.17/10.93 ms**, and local `/score` TestClient median/P95 **11.44/14.30 ms** including JSON validation, response serialization and audit fsync. HTTP counts: `{'200': 120}`. These exclude real network latency, concurrent load, training and startup; reruns change timings.

A separate five-request stress sample with the allowed maximum **20,000 synthetic transaction events** (2152323 body bytes) measured median/P95 **54.05/106.07 ms**. Status counts: `{'200': 5}`. The generated events are repeated for this latency-only check; this is not an additional accuracy sample.

Local inference calls no external API and incurs no per-request provider fee. CPU, memory, storage, operational support and retraining still cost money; no monetary cost estimate was measured. The README lists deployment and validation limitations.

[Machine-readable measured values](metrics.json)
