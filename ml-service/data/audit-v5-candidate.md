# V5 candidate addendum

This addendum records the candidate before constructing the reserved V5 targets.
It supplements [the frozen V5 protocol](audit-protocol-v5.md); its target positions,
generator, synthetic comparator, acceptance gates and bootstrap rules are unchanged.

The selected net policy uses the unchanged, externally audited
`adaptive_revenue_10` real-revenue component, observed `median_share12` costs and
`guard_0.65_0.25_0.25` transfer shares. Real contribution is 65% for supported
histories and 25% for fewer than 12 months or the existing observed inflow-regime
guard. The original real recipe and synthetic comparator remain unchanged.

Selection uses only the original 60 development businesses. All 25 cost options
(24 observed projections and the synthetic benchmark) × 38 transfer policies are
retained with their measured results and rejection reasons. In addition to the
original error gates and 55% development mean-real-share requirement, candidates
must meet a tighter 10% development cohort buffer. Mean shares use accurate
`math.fsum` summation; no subthreshold share is rounded upward. The final audit
still permits at most 15% cohort error regression and requires mean share 50%.

Development MAE is 100.637410565 indices versus 106.089345724 for the synthetic
reference; macro normalized MAE is 0.116933323 versus 0.122606069. Mean real share
is exactly 55% (45 histories at 65%, 15 at 25%). The maximum development cohort
error ratio is 1.088345302. These are development selection measurements.

Two local observed-net reliability experiments each measured 7,296 combinations
and found no majority-qualified policy; their maximum mean share was 41.25%.
A 29,184-combination latest-origin variant qualified some candidates, but was
rejected for additional inference, absent supported local evidence in 31 of 60
histories and slightly worse pooled error. No additional net reliability router
runs in the selected policy. Compact truthful summaries remain in artifact
metadata; the chosen original grid retains every candidate result.

V2 failed the majority-share requirement; V3 and V4 failed cohort error guards.
Their reports and checkpoints remain preserved. This fourth cycle follows known
aggregate rejection signals and is explicitly exploratory sequential development.
No consumed audit target labels or cohort error details choose this candidate.
The separately reserved V5 positions 4,000,000–4,000,899 remain untouched at the
time this addendum is written. Their eventual result must be reported honestly.
