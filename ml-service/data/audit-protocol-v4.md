# Frozen engineering audit v4

Before constructing any new targets, reserve **test-generator positions
3,000,000 through 3,000,899 inclusive**: 900 stochastic businesses, 100 in each
of the nine unchanged generator cohorts. This cohort is separate from all
previous train, validation, v2 and v3 positions.

This is **exploratory sequential development**, following two rejected serving
policies. Preserve both failures and their original protocol documents:

- V2: mean effective real share **0.4969444444444444** missed the **0.50** gate.
  Its error guards passed. See `reports/engineering-audit-v2-rejected.json/.md`.
- V3: fixed 50% real share met the weight gate and overall normalized error
  improved **4.382197570698798%**, but pattern-break normalized error worsened
  **20.727901853928323%**, beyond the **15%** cohort maximum. See
  `reports/engineering-audit-v3-rejected.json/.md`.

Neither failure is rounded away, removed or turned into a pass. A subsequent
pass would describe an unseen generated cohort after sequential development;
it would not imply universally superior accuracy or restore a single-shot
unconditional statistical claim. The earlier cohorts are consumed and cannot
choose another policy.

The next cost-projection and serving policy is fitted/selected using only the
original training and development validation cases. The developer does not
inspect v3 cohort errors or labels for choosing a target-dependent correction.
A development-only mean-share cushion of 0.55 may constrain candidate choice;
the audit's original mean-share threshold remains **0.50**. The previous
structural attempt to require at least 50% for every active request is not an
audit criterion; no new test threshold is added or relaxed.

The real revenue component stays exactly `adaptive_revenue_10`, with unchanged
real estimators, features, source data and pinned recipe. The unchanged
synthetic-net estimator/selection remains the comparator. The generator and
all target definitions remain unchanged. Each business contributes twelve
generated future inflow-minus-outflow months; every expense and net-flow
target remains explicitly **synthetic**, with no real lending/default labels.

**Exactly unchanged acceptance:**

- Macro business normalized MAE is at most `1.02 ×` the synthetic comparator.
- Raw net MAE is at most `1.05 ×` the comparator.
- Every predeclared cohort's normalized MAE is at most `1.15 ×` the comparator.
- Mean actual effective real-component weight is at least **0.50**.
- The selected revenue candidate uses a real-trained estimator.

Scales use only supplied history. Negative, zero and near-zero actual net
months remain in every error measure. Use the same deterministic 2,000-replicate
whole-business bootstrap with seed `20261012`, preserving twelve-month
dependence. Report actual improvements and descriptive 95% intervals separately
from pass/fail, with counts and every cohort retained. Those intervals describe
the current cohort conditional on its frozen policy, without correcting the
sequential development process. Preserve JSON/Markdown before a failing exit.

The original external v2 revenue result remains preserved and consumed.
Subsequent external runs are same-component regression reproductions, requiring
the pinned recipe/candidate and original losses/counts within the documented
`1e-9` absolute tolerance. Net-cost/blend changes do not make real-revenue labels
fresh again. A new revenue recipe requires new reserved real targets.

Do not construct these v4 positions until the next policy is frozen. Do not
retune on this cohort after inspection, claim real expense/capacity validation,
or erase unsuccessful attempts. Public national aggregates still differ from
individual borrower cash receipts; human credit decisions remain required.
