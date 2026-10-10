# Frozen independent audit protocol

This protocol was declared before examining the reserved target labels or running
either audit. Model fitting, candidate routing and blend selection use development
training and validation cases only. The source partitions are recorded in
[external-protocol.json](external-protocol.json); evaluator gates are fixed in
`capacity_ml/evaluate_fresh.py`. Audit results do not permit another selection
round on the same targets.

## New observed revenue audit

The new corpus contains published nominal turnover observations. Eurostat supplies
unadjusted `NETTUR` indices, **2021=100**, from
[sts_trtu_m](https://ec.europa.eu/eurostat/databrowser/view/sts_trtu_m/default/table?lang=en)
under its [reuse policy](https://ec.europa.eu/eurostat/help/copyright-notice).
The UK Office for National Statistics supplies unadjusted all-business retail
**value indices, 2024=100**, from
[DRSI](https://www.ons.gov.uk/businessindustryandtrade/retailindustry/datasets/retailsales/current)
under the [Open Government Licence](https://www.ons.gov.uk/help/terms-conditions).
These are actual national survey aggregates; they are not borrower transactions,
currency amounts, expenses or default labels.

Eurostat uses a fixed taxonomy of 30 EU/EFTA countries and 22 nonoverlapping NACE
trade leaves. Countries are ranked by
`SHA256('external-country-v1:' + 'eurostat:' + ISOcountry)`; the first 18 are
training, the next six validation, and the last six audit. All sectors in a
country stay together. The entire UK ONS provider, including all historical
dates, is excluded from training and selection.

| Partition                | Country groups                                                         | Allowed future targets        |
| ------------------------ | ---------------------------------------------------------------------- | ----------------------------- |
| Eurostat training        | LV, NL, MT, DE, DK, BE, EE, IS, CH, SK, CY, ES, PL, BG, IT, FI, EL, RO | End no later than August 2024 |
| Eurostat validation      | LT, CZ, HU, HR, LU, SI                                                 | September 2024–August 2025    |
| Eurostat audit           | AT, SE, FR, IE, PT, NO                                                 | September 2025–August 2026    |
| Whole-provider ONS audit | GB                                                                     | September 2025–August 2026    |

The fixed source window is September 2006–August 2026. Development training
origins advance every six months. Primary audit histories contain up to 60
months and require at least 24. Missing, suppressed or unreliable observations
remain explicit nulls. An invalid required history/target window or a source
definition break excludes that window with a recorded reason; missing future
audit observations cannot remove otherwise eligible earlier training windows.
No dates, sectors or providers are removed after seeing model errors.

The original whole-US Census proposal was inaccessible through the permitted
download/API route. The FRED workaround prohibited machine-learning use in its
terms. UK ONS replaced that source for access and licensing reasons before audit
target inspection. No Census or FRED observations enter this model.

The external corpus digest frozen before final model selection is
`10ad0fe821c42ec9bb31c5305faf6d959e754ca45f6cba8748d6e89d47751807`.
The evaluator checks the fitted artifact against that digest and rejects ONS
training or selection rows before constructing audit cases.

The primary baseline is fixed seasonal naive: the historical value for the
forecast calendar month, with the documented historical-level fallback when
that month is unavailable. The primary metric averages each series' 12-month
MAE divided by its input-history mean scale. Series receive equal weight;
per-provider metrics and whole-country clustered uncertainty reveal the effects
of unequal coverage. Raw index-point MAE and WAPE stay within each provider's
base year. Cross-provider results use dimensionless normalized errors only.

**Predetermined acceptance:** macro normalized MAE must improve strictly above
0% versus seasonal naive, and neither provider may regress by more than 10%.
A missing reserved provider fails acceptance. This is an engineering release
gate, not a claim about bank capacity or universally highest accuracy.

Report actual windows, unique target months, usable country clusters, quality
exclusions, per-provider and sector results, sMAPE, seasonal MASE, WAPE, and
forecast-horizon slices. WAPE drops no zero or near-zero targets. Both-zero
actual/forecast pairs have zero sMAPE error; short or zero seasonal MASE
denominators are explicitly undefined. A deterministic 2,000-replicate bootstrap
resamples whole country clusters and gives a descriptive 95% improvement interval.
Its seed is `20261011`. The seven intended country clusters are few and correlated;
the interval is not an independent-store confidence guarantee.

Supplementary 3-, 6- and 12-month history stress cases reuse the same actual
targets. They neither increase the unique observation count nor choose or
qualify the frozen model.

## New synthetic net-cash engineering audit

The unchanged business generator reserves **test positions 1,000,000 through
1,000,179 inclusive**. No model or auditor may construct those businesses until
the final candidate is frozen. Their 180 independent generator seeds are
separate from previously examined train, validation and legacy test positions.
Targets are twelve generated future monthly inflows minus outflows. They verify
serving behavior and transfer integration; they are explicitly synthetic, not
evidence of real borrower expenses or lending outcomes.

The comparator is the frozen model's original synthetic-net forecast. The
selected serving forecast is evaluated through the actual scoring function,
including observed-cost or synthetic-expense handling and the reported effective
real-revenue weight. Predeclared cohorts remain separate, with counts shown.

**Predetermined acceptance:** selected macro normalized MAE must be at most
`1.02 ×` the synthetic comparator, raw net MAE at most `1.05 ×`, and every
generator cohort's macro normalized MAE at most `1.15 ×`. Average effective real
weight must be at least **0.50**, and the selected real component must actually
use an estimator fitted on real revenue targets. These tolerances test absence
of a material regression; any improvement and its uncertainty are reported
separately rather than assumed.

Negative and near-zero actual net months remain in all error measures. A
deterministic 2,000-replicate bootstrap resamples complete businesses, preserving
their twelve-month dependence; its seed is `20261012`. Short-history slices,
effective weights, scoring response validity, target/identity hashes and payment
schedule invariants are reported. Human credit decisions and default calibration
are outside this generated cohort's evidence.

## Freeze, reporting and interpretation

`python -m capacity_ml.evaluate_external` writes
`reports/external-metrics.json` and `.md`;
`python -m capacity_ml.evaluate_engineering` writes
`reports/engineering-metrics.json` and `.md`. Both preserve reports and exit
nonzero when a predetermined acceptance rule fails. Reports include the model,
fitted-source and evaluator hashes. There is no fitting inside an evaluator.

Previously examined ABS/Canada terminal periods and synthetic test cohorts are
**consumed legacy regression benchmarks**. New audits are also consumed once
their results inform a later model change. Repeating an unchanged frozen audit
checks reproducibility; it does not create fresh independent evidence. A failed
audit must be disclosed and addressed using new development data and a new
reserved audit, without silently retuning against these labels.

Current snapshots contain revisions and reference-year rebasing rather than
historical release vintages. Source dates are provider-local: development data
from an older provider may occur after another provider's audit period. The
protocol therefore does not establish a globally chronological historical
deployment backtest. Public national revenue aggregates differ from individual
Uzbek business cash receipts; they provide no real expense, repayment, capacity
or default ground truth. Capacity scores remain heuristics with human review.
