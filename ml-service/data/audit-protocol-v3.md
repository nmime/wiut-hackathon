# Frozen engineering audit v3

This document reserves **test-generator positions 2,000,000 through 2,000,899
inclusive**, before constructing any of their targets. It supersedes only the
engineering cohort in [audit protocol v2](audit-protocol-v2.md); its acceptance
thresholds, generator, comparator and metric definitions remain unchanged. The
v2 document and first reports remain preserved.

The first v2 engineering audit rejected the 60% base / 25% reduced real-component
policy: its mean effective real contribution was **0.4969444444444444**, below
the predetermined **0.50** minimum. Its error guards passed. This failure must
not be rounded into a pass, erased or used to loosen a threshold. The report is
preserved as `reports/engineering-audit-v2-rejected.json` and `.md`.

The next policy is selected on the original development validation cases from
the original candidate grid, restricted to policies giving **at least 0.50 real
contribution on every active history**. No v2 target errors, cohorts or future
labels choose that policy. Real revenue estimators, their selected
`adaptive_revenue_10` candidate, features and actual source data remain frozen;
this revision concerns the net-serving composition and truthful guard wording.

The unchanged comparator is the original selected synthetic-net forecast.
Actual serving predictions pass through the scoring function. Each of the 900
new stochastic businesses contributes twelve generated future inflow-minus-
outflow targets. All borrower profiles, expenses and net targets remain
**synthetic**; this is an engineering check, not real lending validation. Each
of the nine fixed generator cohorts has 100 businesses. The larger range was
reserved before constructing any v3 labels, to reduce unstable small-cohort
estimates; the v2 range and its original 180-business result remain unchanged.

**Unchanged acceptance:**

- Macro business normalized MAE is at most `1.02 ×` the synthetic comparator.
- Raw net MAE is at most `1.05 ×` the comparator.
- Every predeclared generator cohort's normalized MAE is at most `1.15 ×`.
- Mean actual effective real-component weight is at least **0.50**.
- The selected revenue candidate uses a real-trained estimator.

Negative, zero and near-zero actual net months remain in the metrics. Scales
come only from supplied history. A deterministic 2,000-replicate whole-business
bootstrap, seed `20261012`, preserves each business's twelve-month dependence.
Report actual improvements and their descriptive 95% interval separately from
these finite-sample no-material-regression tolerances. Preserve results before
exiting nonzero on a failed gate. No fitting or selection occurs in an evaluator.

The original external v2 revenue audit passed its predeclared criteria and is
preserved in `reports/external-audit-v2-frozen.json` and `.md`. Those observed
targets are now **consumed**. Subsequent external runs are regression
reproductions, with equality required for the selected revenue candidate and
pinned recipe covering parameters, features/routing, source-data and dependency
fingerprints before constructing cases. Exact fitted-estimator equality is
recorded locally. Cross-platform same-recipe builds can differ in floating-point
learned bytes; primary overall/provider losses and counts must reproduce the
original report within **1e-9 absolute tolerance**, with no relative tolerance.
This establishes metric reproduction at the stated precision rather than
pointwise identical forecasts or fresh evidence. Net policy or scoring changes do not invalidate
an unchanged revenue predictor's original result; they also do not make those
labels fresh again. A changed revenue predictor needs newly reserved real
targets rather than selecting against the consumed v2 result.

The new engineering positions become consumed after inspection. A later model
revision must not claim the same cohort as fresh. Public revenue aggregates
still supply no borrower expenses, repayment, default or capacity labels;
human review and the transfer limitations in v2 continue to apply.
