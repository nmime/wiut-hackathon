# Fresh-source revenue upgrade protocol

Fixed on 11 October 2026 before comparative errors for this experiment. The
previous real-model comparison is consumed development evidence. This experiment
does not establish borrower expense, repayment or default accuracy.

## Data and reservation

Preserve both original serving artifacts, the first experimental LightGBM, all
original snapshots and frozen reports. New collectors, models and evidence use
separate namespaces. Source selection is based on official availability and
licensing, never model errors.

Add two previously unused datasets. Source availability was resolved before
training or comparative errors: the US Census bulk download returned HTTP 403
and its API required a key; the FRED redistributor's terms prohibit ML use. No
observations from that route enter this experiment.

- Statistics Canada wholesale trade sales, table 20-10-0074-01: original monthly
  nominal sales, thousands of current CAD, under the Statistics Canada Open
  Licence. Exclude adjusted data, overlapping NAICS parents, national and regional
  aggregates. The last full release used is July 2026. Declare the complete
  disjoint leaf taxonomy and provincial geography set in the source manifest.
  Sort geographies by SHA-256 of `20261011|geography`; the first
  `max(3, ceil(number_of_geographies / 3))` are entirely audit-only. Remaining
  geographies supply rolling training targets ending no later than July 2024,
  development targets August 2024–July 2025, and one final August 2025–July 2026
  window. Audit-only geographies supply nine disjoint annual target blocks
  starting August 2017 through August 2025. Canadian retail observations were
  used previously; this is a fresh wholesale dataset and targets, not an
  independent new country or publisher. Shared Canadian economic shocks remain.
- Statistics New Zealand electronic card transactions: monthly Actual dollar
  spending in millions of NZD, eight disjoint published leaf industries. The
  complete country/provider is audit-only. Reserve nine disjoint annual target
  blocks starting September 2017 through September 2025 and ending August 2026.
  Card spending is a revenue proxy, includes GST, and does not cover all merchant
  revenue. Record the revised/backcast classification vintage explicitly.

If the expected endpoint is unavailable, resolve and document the last published
full month before any model comparisons. Never substitute unpublished outcomes.
Use at most 60 supplied historical months and at least 24 for fresh full cases.
Missing, suppressed, unreliable, nonfinite and negative observations exclude a
whole affected window; observed zeros remain zeros. No imputation, fabricated
transactions, expense labels or currency conversion is permitted.

Before training or comparative errors, freeze the snapshot, license, source/raw
hashes, taxonomy, split membership, counts, exclusions, full case histories,
target-coordinate hashes and target-value hashes. Assert new provider identities
are absent from every previous snapshot/benchmark, that own fitting/development
targets and histories never include final target coordinates, and audit-only
sectors/providers never enter fitting or development. Final windows may supply
past observations to later final histories; that is declared retrospective
rolling evaluation, not independent samples. Do not select target dates, sectors
or exclusions from forecast errors.

Training adds only the new Canadian wholesale fitting partition to the original 7,248 real
training origins. Original validation plus all previously measured terminal and
reserved temporal windows are now development/regression checks, without being
added to fitting. ONS remains absent from fitting; its previously measured
forecasts may be development evidence now and are no longer an untouched audit.
Every case receives equal target-month weight within its provider, and providers
receive equal total training weight. For each origin, augment with unique
available histories of 3, 6, 12 and full supplied months. Divide that origin's
weight among its views; repeated labels are not extra unique observations.

This is a new-label and new-source retrospective holdout. Published revised
vintages, shared national/global economic shocks and historical periods prevent
a prospective historical-vintage or independent-bank validation claim.

## Bounded improvement and development selection

The upgraded model retains the original 21 history-derived revenue features and
adds fixed features measuring observed lag support, robust levels, trends,
volatility, zero shares, seasonality and baseline disagreement. No provider,
sector, absolute currency or future outcome features are supplied. Freeze the
complete feature names and feature-source hash before development predictions.
History-only seasonal phase and monetary-scale invariance are required.

Exactly eight deterministic LightGBM configurations are allowed:

- Anchors: `damped_seasonal` and `flat_harmonic`.
- Objectives: L1 log residual and L1 normalized linear residual.
- Leaves: 15 and 31; 400 rounds, learning rate 0.04, minimum leaf size 60,
  L2 penalty 5, maximum depth 6, seed 20261011, one CPU thread.
- Log target is `log(actual/scale + .05) - log(anchor/scale + .05)`;
  reconstruction clips residual to ±3, then applies the inverse and clips
  negative reconstructed revenues to zero.
- Linear target is `actual/scale - anchor/scale`; reconstruction is
  `max(anchor/scale + clip(residual, -5, 5), 0) * scale`.
- `scale` is the positive mean of the latest up to twelve supplied historical
  revenue months, never future outcomes.

For each configuration consider fixed incumbent weights 0, .25, .5, .75 and 1;
identical all-incumbent endpoints collapse to one of 33 unique candidates. The
frozen synthetic-trained teammate receives no weight. There is no post-error
configuration expansion, provider-specific mixture or final-label routing.

Measure full development histories and separate 3/6/12-month stresses. Choose
the lowest equally provider-weighted normalized MAE among candidates worsening
no full-history provider by more than 2%, and worsening no pooled stress slice
by more than 2% against incumbent. Ties within 1e-12 choose the greater incumbent
weight, then lexicographically smaller configuration. A candidate requires at
least 5% full development error reduction for replacement eligibility. If none
passes, freeze the best non-incumbent guarded candidate as a diagnostic, or the
best unconstrained candidate if no guarded challenger exists; retain the
incumbent. Freeze selection, training/input/model/source/dependency/protocol
hashes and mixture weight before preparing final inference. Final inference
executes only that frozen configuration; alternatives never receive final scores.

## Fresh evaluation and promotion

Compare incumbent, frozen previous third model, seasonal naive and the selected
upgrade on identical histories. Raw monetary errors are reported only within
one provider's declared units; provider-balanced normalized case MAE is primary.
Also report WAPE, sMAPE, seasonal MASE, counts and quality exclusions. Every
required case must return twelve finite nonnegative aligned predictions; no
silent refusals, exclusions or fallback after errors.

The primary fresh panel combines nine annual blocks for Canadian audit-only geographies
and all NZ sectors. Separately report the most recent block for all Canadian wholesale and NZ
sectors. Use paired 2,000-draw bootstrap, seed 20261011, resampling whole annual
blocks with replacement while retaining all sectors and geographies within a block. The Canadian
August and NZ September origins map to the same start-year block; paired block
draws across providers retain shared global-shock dependence. This has only nine
temporal blocks and two countries, is descriptive, and does not estimate
arbitrary future-country uncertainty. Do not bootstrap sectors as independent
businesses. Latest-only results have one annual block per country and do not
receive a misleading independent-sector confidence interval.

A default revenue-component replacement is authorized by the user's conditional
request only when every gate passes:

1. Development eligibility as defined above.
2. At least 5% primary fresh-panel normalized MAE reduction and paired annual
   block bootstrap 95% lower improvement bound above zero.
3. No provider regresses by more than 2% on either primary or latest-only panel;
   latest-only provider-balanced gain must also reach 5%.
4. No 3/6/12-month primary-panel stress worsens by more than 2% in balanced error.
5. All predictions valid, identities verified, and downstream transport,
   monetary units, capacity guards, audit durability and product checks pass.

If any revenue gate fails, keep the current revenue component and record the
failure; never relax the gate or tune against final results. A replacement
requires explicit versioned runtime packaging, verified model/dependency/source
identities and original artifact reproducibility. After inspection, the new
final labels are consumed for any later cycle.

## Real revenue uncertainty and the combined financial layer

The user's subsequent full-merge instruction authorizes one combined default
scorer with 24% APR, twelve-month seasonal plans, schedule-aware affordability,
three advisory verdicts and a sustained-decline guard. This financial policy
change is separate from the conditional revenue replacement above. It uses the
incumbent real revenue component if the upgrade fails; original scorers and
their frozen evidence remain reproducible alternatives. No remote deployment
or Git branch merge is included.

Before final scoring calibrate a 99-level revenue quantile grid from real
DEVELOPMENT residuals only. Exclude all histories/views of the 68 original
external-audit target windows (49 Eurostat and 19 ONS) from residual calibration;
their previously consumed results are reported again only as a diagnostic.
Separate histories shorter than twelve months from histories at least twelve
months, and horizons 1–3, 4–6, 7–12. Normalize signed residuals by each case's
historical scale. Each provider has equal total calibration weight within a
bucket. Use fixed weighted empirical quantiles .01 through .99, constrain lower
quantile offsets to be nonpositive and upper offsets nonnegative, and fix .50
offset to zero to preserve the frozen median forecast. Revenue lower bounds are
floored at zero. There is no interval-width optimization using audit/final
labels. Freeze separate grids for incumbent and selected upgrade before final
inference, then use the grid belonging to the eventual chosen median.

Report actual fractions of real observations above P10 (nominal90%) and P20
(nominal80%), and inside P10–P90 (nominal80%), on the 68-series diagnostic and
the fresh primary/latest panels. These empirical, dependent, retrospective
residual grids are not a formal exchangeability or borrower coverage guarantee.
They calibrate REVENUE only. Project expenses using the incumbent's frozen
observed-cost policy on actual borrower history; public data supplies no expense
labels and therefore cannot select a superior expense model. Total observed
outflows already include any unclassified debt; do not add invented debt or
counterparty categories. Free-flow uncertainty additionally depends on the
unvalidated expense assumption and must be disclosed.

Keep native vendor code and its SHA manifest unchanged; reuse verified
amortization/adaptive solver mechanics in a new financial layer. Compute tier
amounts against the same seasonal payment constraints actually offered. A wide
P10/P20 band alone cannot decline a business with usable positive median
capacity: flag an elevated-risk, human-review tier. Sustained decline or no
usable median repayment capacity suppresses a positive main-tier recommendation.
Scores must describe the same offered capacity/risk tier as amounts. A human
records every final review decision and every attempt is durably audited.

Engineering fixtures must cover declining and seasonal histories, genuine
interest conservation, score/amount consistency, requested limits, twelve-month
alignment and same-principal fixed-versus-seasonal payment exceedance counts.
Those fixtures and simulated future free flow are synthetic behavior checks,
never real-data borrower accuracy. Real revenue tests, financial invariants,
transport/API/integration/browser tests and complete identities are separate
validation layers.
