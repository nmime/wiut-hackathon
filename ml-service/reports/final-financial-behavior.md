# Synthetic financial behavior checks

**All borrower histories, quantile grids, expenses and future surplus below are disclosed synthetic fixtures. These checks establish code behavior, not real borrower accuracy, repayment safety or default probabilities. No fixture was imported into an active portfolio.**

The measured engine reuses the frozen native loan primitives at **24% annual nominal interest (2% monthly)** and a twelve-month term. Every paired comparison holds principal, interest rate and term constant. Separate synthetic future-surplus arrays enter the descriptive backtest only after the assessment is frozen.

| Synthetic scenario               | Advisory verdict     | Tier | Offered principal, UZS | Score | Offered overload months | Annuity overload months | Offered interest, UZS | Annuity interest, UZS |
| -------------------------------- | -------------------- | ---- | ---------------------: | ----: | ----------------------: | ----------------------: | --------------------: | --------------------: |
| seasonal_expected_future         | affordable           | p10  |           2,326,649.90 | 100.0 |                       0 |                       7 |            293,274.07 |            313,435.01 |
| seasonal_unexpected_flat_future  | affordable           | p10  |           2,326,649.90 | 100.0 |                       4 |                       0 |            293,274.07 |            313,435.01 |
| wide_interval_positive_median    | elevatedrisk_officer | p50  |           1,004,657.41 |  50.5 |                       0 |                       0 |            135,342.58 |            135,342.58 |
| same_month_persistent_decline    | decline              | none |                   0.00 |   0.0 |                       — |                       — |                     — |                     — |
| median_six_nonpositive_months    | decline              | none |                   0.00 |   0.0 |                       — |                       — |                     — |                     — |
| short_six_month_history          | affordable           | p10  |             964,471.11 | 100.0 |                       0 |                       0 |            129,928.88 |            129,928.88 |
| insufficient_three_month_history | decline              | none |                   0.00 |   0.0 |                       — |                       — |                     — |                     — |

The expected seasonal future demonstrates lower payments in weak months without applying a fixed-annuity affordability cap. The unexpected flat future retains a case where that seasonal offer has **more overloaded months** than the same-principal annuity; the scorer cannot observe that future in advance.

Wide P10/P20 uncertainty with feasible positive P50 becomes an elevated-risk officer recommendation. Same-calendar observed decline, six nonpositive median surplus months and insufficient history suppress principal and score. A six-month history uses annuity rather than unsupported annual seasonality.

Overload months count deficits above the native 1 UZS tolerance; overload volume is the sum of all positive payment deficits. Interest totals differ because repayment timing changes the outstanding balance, despite identical principal, 24% annual rate and twelve-month term. Future costs are assumed observed-total-outflow projections; these fixtures do not validate that assumption.

Real revenue-grid calibration and fresh forecast evidence are evaluated separately. Revenue intervals do not establish calibrated net-flow, default or repayment probabilities. Native P10/P20 buffers remain disclosed synthetic policy, and a human officer records the final decision.

The companion JSON retains full synthetic inputs, frozen forecasts, actual offered and annuity amortization rows, tier budgets, guard diagnostics and identities:

- `final-financial-behavior.json`
- Frozen native model SHA-256: `51091e827f0b9d768878bd8e414e2c10dd18c7e3dee884acb3680b722bfa8d1a`
- Scorer SHA-256: `9f4a7fb8eaf63009cabb41940ef20ca957cf3d32aae7e46770150927555b5e35`
- Transport SHA-256: `df103933ec7904a092adc887e38b2f62cab6551e22e1cfb79e51f03c6adc2607`
- Disclosed fixture source SHA-256: `24d71c4d17b82abc41835dd417cb0cd13a10c35a4a1f133ab382accbdbbf27ea`
- Backtest source SHA-256: `c90b63acff62c76360fbf73cf106e06aae4a58ca767b7b47fd14b75958bf69f1`

## Actual frozen provider integration

These additional borrower histories remain **synthetic fixtures**, now scored through the actual release provider and its real-development revenue calibration. No real borrower accuracy or repayment labels are asserted. Revenue training, selection and calibration remained frozen.

| Synthetic input               | Verdict    | Tier | Principal, UZS | Score | Offered budget overload months | Retained history |
| ----------------------------- | ---------- | ---- | -------------: | ----: | -----------------------------: | ---------------: |
| actual_provider_seasonal      | affordable | p10  |   1,259,994.26 |  92.7 |                              0 |               24 |
| actual_provider_decline       | decline    | none |           0.00 |   0.0 |                              — |               24 |
| actual_provider_one_month     | decline    | none |           0.00 |   0.0 |                              — |                1 |
| actual_provider_two_months    | decline    | none |           0.00 |   0.0 |                              — |                2 |
| actual_provider_partial_month | affordable | p10  |     618,240.86 |  91.9 |                              0 |               23 |
| actual_provider_partial_only  | decline    | none |           0.00 |   0.0 |                              — |                1 |

The seasonal actual-provider case has positive median surplus and a positive actual offered schedule. Rounded settled payments satisfy the same **1 UZS** budget tolerance used in overload counting; feasibility search uses integer-cent principal candidates. Sustained same-calendar decline with a positive requested amount records `declined_by_guard`, zero principal and zero score. One- and two-month histories disclose below-calibration support and receive zero main recommendation. A cutoff on December 11 excludes December, retaining 23 complete months; a partial-only one-month history is retained and also declines.

One real public aggregate observed-history case, `statcan_wholesale:Alberta:4131|2017-08|full`, reproduces the previously saved current point predictions **bitwise exactly using the frozen mean-100 preparation and rescaling path**. Direct original-history inference differs only by `4.656612873077393e-10` original numerical series units from floating-point operation order; it is not claimed bitwise identical. Under a mean-100 test amount-index transform, maximum absolute difference is `1.4210854715202004e-14` (tolerance rtol = 1e-12, atol = 1e-10); changing observed outflow leaves revenue points bitwise unchanged. Future outcome labels were not accessed for this check. It validates frozen inference, not forecast accuracy or monetary transfer to real borrowers.
