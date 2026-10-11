# Real aggregate revenue comparison protocol

Preregistered on 2026-10-11 before this experiment reads comparative model errors.
This is an exploratory retrospective component comparison on published revenue
aggregates. Existing final panels are consumed evidence for the incumbent. They
cannot provide a fresh confirmatory claim, borrower affordability validation,
repayment validation, or default probability validation.

## Scope and frozen inputs

Compare monthly revenue forecasts, never net cash flow or capacity scores:

- The existing frozen `adaptive_revenue_10` real-revenue component, without its
  synthetic net-flow blend, expense projection, scoring, or schedule logic.
- The teammate's frozen LightGBM inflow component, verified against the vendor
  manifest; no retraining, weight mutation, or calls to its outflow/capacity/LLM
  path. Its training metadata identifies synthetic businesses.
- One exploratory real-trained LightGBM residual component fitted only to the
  same explicit real training splits as the incumbent revenue component.
- Seasonal naive as a reference. Fixed mixtures defined below are exploratory
  candidates rather than independent new models.

Record source/data/dependency/artifact hashes, model versions, exclusions, case
identities, target dates, history lengths and actual counts. Preserve all frozen
reports and artifacts. Do not overwrite the existing model, default provider, or
previous evaluation reports. Model/data selection is complete before terminal
errors are measured. No new data source is chosen using forecast errors.

## Data isolation and panels

Use the existing committed snapshots, license declarations, methodology breaks,
geographic splits, and missing/suppressed/unreliable-value exclusions. Invalid
observations are excluded; observed zero revenue remains zero. Do not impute
missing observations or convert aggregate revenue into invented transactions.

Development consists only of these existing validation windows:

| Provider          | Builder                                              | Split        | Target period     | Valid cases / observed months / groups |
| ----------------- | ---------------------------------------------------- | ------------ | ----------------- | -------------------------------------- |
| Uzbekistan SIAT   | `public_revenue.build_cases(*load_revenue_series())` | `validation` | Jan-Dec 2025      | 32 / 384 / 3                           |
| ABS Australia     | `build_international_cases("validation", dataset)`   | `validation` | Jul 2023-Jun 2024 | 30 / 360 / 2                           |
| Statistics Canada | same explicit international builder                  | `validation` | Aug 2024-Jul 2025 | 29 / 348 / 3                           |
| Eurostat          | `build_external_cases("validation", dataset)`        | `validation` | Sep 2024-Aug 2025 | 44 / 528 / 5                           |

ONS is audit-only and absent from development at every date. Every sector record
from one geography remains in its existing group. The Uzbekistan builder returns
all splits together; selection code must consume only its `train`/`validation`
keys and must not compute final errors or final target summaries before freeze.
International/external builders take one explicit split. Importing source files
does not permit passing future targets to a model. Each model sees only a case's
history ending before its forecast start; calendar features may use public future
calendar dates. No provider, geography or target-derived labels enter routing.

After selection is saved and hashed, measure the existing terminal panels:

| Provider          | Existing split       | Target period                                           | Valid cases / observed months / groups |
| ----------------- | -------------------- | ------------------------------------------------------- | -------------------------------------- |
| Uzbekistan SIAT   | `test_2025`          | Jan-Dec 2025, held-out geographies                      | 70 / 840 / 3                           |
| Uzbekistan SIAT   | `test_2026`          | Jan-Aug 2026 only; remaining forecast months unobserved | 70 / 560 / 3                           |
| ABS Australia     | international `test` | Jul 2024-Jun 2025                                       | 24 / 288 / 2                           |
| Statistics Canada | international `test` | Aug 2025-Jul 2026                                       | 32 / 384 / 2                           |
| Eurostat          | external `audit`     | Sep 2025-Aug 2026                                       | 49 / 588 / 5                           |
| ONS Great Britain | external `audit`     | Sep 2025-Aug 2026                                       | 19 / 228 / 1                           |

Counts were constructed without model predictions or comparative error reads.
Development exclusions are Uzbekistan 66, ABS 0, Canada 31 and Eurostat 88.
Terminal exclusions are Uzbekistan 26 in each panel, ABS 6, Canada 28, Eurostat
83 and ONS 0. Most are missing/suppressed/unreliable windows; Eurostat validation
also excludes one definition-break window. Entire excluded geographies must not
be described as present: Canada terminal has 2 valid groups of 3 intended and
Eurostat terminal 5 valid countries of 6 intended. Training contains 740
Uzbekistan, 1,707 ABS, 1,000 Canada and 3,801 Eurostat cases, totaling 7,248 rolling
cases / 86,976 target-month examples, with overlapping targets explicitly
dependent.

Dates are provider-local, and later Uzbekistan training labels overlap earlier
foreign terminal dates. This is not a globally chronological future experiment.
Revised current-vintage aggregates are not historical-vintage bank backtests.

## Fair revenue-only adapter

For each case, define `scale` as its positive mean inflow over the latest up to
12 supplied historical months. Rescale supplied inflow by `100 / scale` so its
recent level is 100, preserving exact month identifiers and history length.
This prevents the teammate's additive log pseudocount (`0.05 * level + 1`) from
giving currencies and provider index bases arbitrary unequal treatment. Apply
the same representation to the incumbent and new real-trained component and
rescale every predicted revenue back by `scale / 100` before measurement.
Normalization never uses future actuals.

The vendor profile receives actual monthly revenue and calendar only. Unknown
operating/fixed/debt expenses, QR/card/transfer/cash shares, payer concentration,
active days, and industry prior are `NaN`, with no invented zero, channel or
activity labels. Read only the inflow booster and its existing anchor/residual
prediction, not full `predict_business` net/debt/conformal scoring. LightGBM may
route missing features; this missing-feature aggregate transfer is a material
scope limitation, which must be reported. The incumbent's internal neutral zero
second array remains a revenue feature representation, not expense observations.

Forecast all 12 calendar months and score only the case's observed horizon.
Require aligned finite nonnegative revenue predictions. The frozen vendor's
minimum six-month support rule is retained: an expected refusal for fewer than
six historical months uses the incumbent forecast for that vendor share in a
mixture. This fallback is fixed before errors and is an explicit mixture policy,
not a claim that the vendor independently supports such histories. Report native
vendor requested/supported/refused counts, refusal codes, all-case fallback
mixture metrics, and a separate common-support comparison. Unexpected refusals,
execution failures, or invalid outputs fail eligibility and are never replaced
silently by the incumbent. Both frozen components use identical requested cases
and history windows.

## Bounded real-trained variant and fixed mixtures

The exploratory LightGBM uses the incumbent `revenue_feature_matrix` and learns
the log residual to `damped_seasonal`, with the same target formula and history
normalizer as the existing real-trained residual model. Its preregistered
reconstruction is `max(exp(log(damped / scale + 0.05) + clip(residual, -3, 3)) -
0.05, 0) * scale`. The residual bound of three is an experimental choice that
differs from the frozen model's bound of two; it is not chosen from final errors.
No synthetic revenue targets enter fitting. Each provider receives equal total
training loss weight; overlapping rolling origins are not independent examples.

The fixed four-configuration grid is:

- Objective L1, learning rate 0.04, minimum leaf size 60, L2 penalty 1, seed
  20261011; no early stopping using terminal labels.
- `num_leaves` in `{15, 31}` and boosting rounds in `{200, 400}`.
- Select the best configuration satisfying the two-percent development provider
  gate if any does; otherwise select the best unconstrained configuration as a
  diagnostic. Within that set minimize provider-balanced development normalized
  MAE; ties within `1e-12` choose fewer leaves, then fewer rounds.
- For replacement consideration it must improve overall development error by at
  least 5% against the frozen incumbent and worsen no provider by more than 2%.
  Report the best unconstrained configuration even if none qualifies, without
  calling it a replacement.

Then consider the finite convex mixture grid with weights for
`(incumbent, frozen_vendor, selected_real_lgb)` drawn from
`{0, 0.25, 0.5, 0.75, 1}` and summing exactly to 1. This is 15 mixtures, including
the three endpoints. Select on the same development metric and provider gates;
ties choose the largest incumbent weight, then the smallest vendor weight. The
incumbent remains an explicit fallback. No target-driven or per-series routing,
provider-specific weights, fitted mixture coefficients, terminal-label tuning,
or post-error grid expansion is permitted.

## Metrics and decision rules

The primary metric is mean case-level history-normalized MAE within provider,
then the equally weighted mean across providers. Report each provider and each
terminal panel separately; pool both Uzbekistan panels within its provider with
equal case weight, preserving differing observed 8/12-month horizons. Also show
normalized WAPE, sMAPE, seasonal MASE with short/zero-denominator exclusions, and
raw MAE only within declared compatible provider units. Do not pool raw currency
or provider index errors. Retain zero and near-zero months in MAE/WAPE/sMAPE and
report the zero-denominator policy. Do not label MAE improvements as accuracy.

A frozen selected challenger warrants further replacement consideration only if
development eligibility passed, terminal provider-balanced MAE improves against
incumbent, no provider terminal error regresses more than 10%, all cases produce
valid predictions, and the lower endpoint of the paired whole-geography
bootstrap descriptive 95% improvement interval is above zero. This finite
retrospective gate is not authority to change the production default.

Bootstrap is paired and stratified by provider: resample entire declared
geography groups with replacement within provider, retain all their sectors and
all target windows together, recompute the provider-balanced primary metric.
Use 2,000 replicates and seed 20261011. ONS has only one country group; its losses
remain fixed within this bootstrap, which cannot estimate UK cross-country
uncertainty. Small correlated cluster counts and sequential prior model work
limit all intervals; report them as descriptive, not confirmatory significance.

Preregister descriptive stress views with 3, 6, 12 and 24 final historical months,
where available, on the same terminal actuals. These reuse labels and cannot
choose the winner. Report short-history/no-support failures and observed-horizon
counts. Vendor uncertainty from synthetic conformal residuals is not calibrated
on these real aggregates and is outside this point-forecast comparison.
Optional unnormalized vendor predictions in native source units may be reported
as a scale-sensitivity diagnostic only; they cannot select the primary transform,
candidate or mixture. The vendor's missing-feature transfer and synthetic
uncertainty limitations remain unchanged.

## Unused retrospective possibilities

Existing snapshots may contain post-training-cutoff targets for original
training geographies (Uzbekistan 2026; ABS 2024-25; Canada 2025-26; Eurostat
2025-26), 2026 targets for Uzbekistan validation geographies, and earlier windows
for wholly held-out ONS. These should be considered only by a deterministic
calendar/geography rule after verifying exact target-coordinate disjointness
from fitting, development, and every previously reported target panel. Some
candidate targets were supplied as history in an existing audit, or lie in
previously examined economic periods; these are not untouched data in a broad
sense. No such extra panel enters this experiment's selection or acceptance
gate. Do not hunt for successful dates, countries, sectors or sources after
errors. A future fresh test needs newly reserved targets and a new protocol.

A count-only deterministic check of existing terminal periods on original
training geographies found these candidates, each with zero overlap against
target coordinates from all existing train/validation/final builders:

| Retrospective candidate                             | Valid cases | Observed months | Geography groups |
| --------------------------------------------------- | ----------: | --------------: | ---------------: |
| Uzbekistan Jan-Aug 2026, original train groups      |         177 |           1,416 |                8 |
| Uzbekistan Jan-Aug 2026, original validation groups |          32 |             256 |                3 |
| ABS Jul 2024-Jun 2025, original train groups        |          52 |             624 |                4 |
| Canada Aug 2025-Jul 2026, original train groups     |          95 |           1,140 |                7 |
| Eurostat Sep 2025-Aug 2026, original train groups   |          92 |           1,104 |               16 |

These targets are now reserved before comparative errors as an additional final
panel named `unused_temporal_full`, using the exact deterministic case/target
coordinate hashes in `ml-service/data/real-comparison-unused-temporal.json`.
They are never used for fitting, development selection or coefficient tuning.
They reuse known geographies and economic periods and a single revised snapshot;
the newly reserved retrospective temporal check is not independently fresh
providers, bank validation, or a confirmatory single-shot statistical claim.
Earlier
ONS observations are already supplied as terminal-audit history; they do not
form broadly untouched data merely because they were not target labels.

For further replacement consideration the selected candidate must also pass
this additional panel: at least five-percent provider-balanced MAE improvement
against incumbent, no provider regressing by more than ten percent, all required
forecasts valid (with only the predeclared short-history fallback), and paired
whole-geography bootstrap descriptive 95% interval lower endpoint above zero.
A failure on either final panel means retain the incumbent. A pass remains
exploratory evidence requiring the user's separate authority to change serving.
Verify all reserved target coordinates are disjoint from original real training,
development, existing final/audit panels, and the original public retail
baseline train/validation/test coordinates, including alias mapping from retail
code to the shared `retail:code` identity. Preserve Eurostat methodology flags and
all providers' temporal/history bounds. Freeze sorted case identities, target
coordinates, target values, source hashes, exclusions and counts in the tracked
manifest before any predictions on this panel. Unknown ad hoc prior access
outside committed builders cannot be ruled out and must be disclosed.
