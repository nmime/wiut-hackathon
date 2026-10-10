# Uzbekistan public-revenue regression benchmark

Measured 2026-10-10T20:52:13.397341+00:00; artifact `local-v4-bf33fb45ddc3-gradient_boosting-public65`. Reproduce with `uv run python -m capacity_ml.train` and `uv run python -m capacity_ml.evaluate_revenue`.

These fixed Uzbekistan evaluation periods were reported before this model upgrade. They are now **legacy regression benchmarks**, not fresh confirmatory holdouts. Targets remain excluded from fitting and validation selection. See the [external-provider audit](external-metrics.md) for separately reserved final observations. The international evaluation is now also a previously reported regression benchmark.

The offline corpus contains **16,544 published monthly observations** across retail, wholesale, district market services and accommodation/food service aggregates. Excluding national and parent totals, then respecting the service methodology boundary, leaves **440 eligible series / 11,716 observations**. These counts include retained source revisions; invalid forecasting windows are excluded rather than corrected or clipped.

The Uzbekistan portion supplies **740 rolling windows / 8,880 actual target-month examples** from **187 series**, representing **2,797 unique target observations**. The combined Uzbekistan/Australia/Canada/Eurostat model uses **86,976 actual target examples**; overlapping windows are not independent records. Uzbekistan targets end by December 2025. Regions are partitioned by a fixed hash into 8 training, 3 validation and 3 legacy test groups; all sectors/districts of a region stay together. Pre-2025 retail/wholesale histories are capped at 48 months. Post-break service histories before January 2025 contain only 3 months and are a cold-history limitation.

Uzbekistan development validation covers January–December 2025 in independent geographic groups. The combined model selects **adaptive_revenue_10** by provider-balanced macro normalized validation MAE, giving each provider equal weight. The table below shows only the Uzbekistan validation slice, which may prefer a different candidate. Test targets remain excluded from fitting and selection. Source-revision exclusions: `{'train': 274, 'validation': 66, 'test_2025': 26, 'test_2026': 26}`. The 2025 legacy evaluation is an entity holdout; the 2026 evaluation also follows Uzbekistan training in time. Only January–August 2026 is published: the last four forecast months are unobserved and excluded.

Valid-window composition: `{'train': {'accommodation_food': 80, 'market_services': 91, 'retail': 366, 'wholesale': 203}, 'validation': {'accommodation_food': 11, 'market_services': 18, 'retail': 3, 'wholesale': 0}, 'test_2025': {'accommodation_food': 27, 'market_services': 40, 'retail': 3, 'wholesale': 0}, 'test_2026': {'accommodation_food': 26, 'market_services': 40, 'retail': 3, 'wholesale': 1}}`. In particular, source revisions exclude wholesale from validation and the 2025 holdout; its one 2026 case cannot establish sector-wide performance. The geographic validation group is small and uneven after exclusions.

| Candidate               | Validation normalized MAE | Validation MAE (million UZS) | Validation MAPE (%) |
| ----------------------- | ------------------------: | ---------------------------: | ------------------: |
| seasonal_naive          |                     0.247 |                   53,893.364 |              52.622 |
| trend_adjusted_seasonal |                     0.241 |                   45,408.211 |              52.428 |
| damped_seasonal         |                     0.239 |                   39,231.440 |              52.081 |
| robust_harmonic         |                     0.258 |                   58,816.725 |              53.273 |
| linear_harmonic         |                     0.258 |                   57,783.297 |              53.025 |
| flat_harmonic           |                     0.262 |                   64,642.135 |              53.178 |
| gradient_boosting       |                     0.174 |                   38,179.680 |              43.742 |
| learned_residual        |                     0.164 |                   34,910.348 |              42.456 |
| residual_blend_25       |                     0.212 |                   37,191.834 |              48.939 |
| residual_blend_50       |                     0.188 |                   35,828.019 |              46.050 |
| harmonic_residual_25    |                     0.230 |                   51,821.670 |              50.181 |
| harmonic_residual_50    |                     0.203 |                   46,177.895 |              47.483 |
| harmonic_residual_100   |                     0.169 |                   38,127.080 |              43.659 |
| history_shrinkage_25    |                     0.163 |                   34,424.863 |              42.369 |
| history_shrinkage_50    |                     0.163 |                   34,544.428 |              42.389 |
| adaptive_revenue_0      |                     0.165 |                   35,919.965 |              42.489 |
| adaptive_revenue_5      |                     0.164 |                   34,910.348 |              42.456 |
| adaptive_revenue_10     |                     0.164 |                   34,910.348 |              42.456 |
| adaptive_revenue_15     |                     0.164 |                   34,910.348 |              42.456 |

## test 2025

Valid series: 70; excluded complete windows: 26. Candidates below are reported after validation selection is fixed.

| Candidate               | Months | Normalized MAE | MAE (million UZS) | MAPE (%) | WAPE (%) |
| ----------------------- | -----: | -------------: | ----------------: | -------: | -------: |
| seasonal_naive          |    840 |          1.402 |        46,121.144 |   61.138 |   19.197 |
| trend_adjusted_seasonal |    840 |          1.398 |        38,396.802 |   60.976 |   15.982 |
| damped_seasonal         |    840 |          1.398 |        37,920.584 |   60.914 |   15.784 |
| robust_harmonic         |    840 |          1.416 |        48,775.042 |   60.594 |   20.302 |
| linear_harmonic         |    840 |          1.415 |        47,874.806 |   60.499 |   19.927 |
| flat_harmonic           |    840 |          1.416 |        49,985.220 |   60.513 |   20.806 |
| gradient_boosting       |    840 |          1.392 |        30,801.592 |   54.634 |   12.821 |
| learned_residual        |    840 |          1.388 |        30,640.696 |   54.967 |   12.754 |
| residual_blend_25       |    840 |          1.385 |        34,938.101 |   58.412 |   14.543 |
| residual_blend_50       |    840 |          1.376 |        32,250.604 |   56.304 |   13.424 |
| harmonic_residual_25    |    840 |          1.398 |        42,185.408 |   57.771 |   17.559 |
| harmonic_residual_50    |    840 |          1.385 |        36,750.449 |   55.487 |   15.297 |
| harmonic_residual_100   |    840 |          1.390 |        29,825.068 |   53.534 |   12.414 |
| history_shrinkage_25    |    840 |          1.388 |        30,494.997 |   54.972 |   12.693 |
| history_shrinkage_50    |    840 |          1.388 |        30,481.080 |   54.968 |   12.687 |
| adaptive_revenue_0      |    840 |          1.388 |        30,640.696 |   54.967 |   12.754 |
| adaptive_revenue_5      |    840 |          1.388 |        30,640.696 |   54.967 |   12.754 |
| adaptive_revenue_10     |    840 |          1.388 |        30,640.696 |   54.967 |   12.754 |
| adaptive_revenue_15     |    840 |          1.388 |        30,640.696 |   54.967 |   12.754 |

| Selected-model sector | Cases | Months | Normalized MAE | MAE (million UZS) | MAPE (%) |
| --------------------- | ----: | -----: | -------------: | ----------------: | -------: |
| accommodation_food    |    27 |    324 |          3.319 |         3,688.344 |  109.185 |
| market_services       |    40 |    480 |          0.178 |        27,517.929 |   22.150 |
| retail                |     3 |     36 |          0.137 |       314,848.755 |   12.100 |

MAPE excludes **5 zero-actual months**. Near-zero positive values remain included, so percentage errors can be large even when aggregate WAPE improves.

## test 2026

Valid series: 70; excluded complete windows: 26. Candidates below are reported after validation selection is fixed.

| Candidate               | Months | Normalized MAE | MAE (million UZS) | MAPE (%) | WAPE (%) |
| ----------------------- | -----: | -------------: | ----------------: | -------: | -------: |
| seasonal_naive          |    560 |          0.312 |        66,544.133 |   44.502 |   21.993 |
| trend_adjusted_seasonal |    560 |          0.307 |        53,636.825 |   44.103 |   17.727 |
| damped_seasonal         |    560 |          0.309 |        58,503.008 |   44.245 |   19.336 |
| robust_harmonic         |    560 |          0.365 |        56,749.751 |   85.064 |   18.756 |
| linear_harmonic         |    560 |          0.366 |        58,366.383 |   85.023 |   19.290 |
| flat_harmonic           |    560 |          0.366 |        60,427.514 |   85.035 |   19.972 |
| gradient_boosting       |    560 |          0.284 |        44,038.416 |   81.809 |   14.555 |
| learned_residual        |    560 |          0.265 |        42,928.298 |   65.327 |   14.188 |
| residual_blend_25       |    560 |          0.252 |        47,185.906 |   43.612 |   15.595 |
| residual_blend_50       |    560 |          0.228 |        40,613.671 |   47.873 |   13.423 |
| harmonic_residual_25    |    560 |          0.334 |        52,465.652 |   83.631 |   17.340 |
| harmonic_residual_50    |    560 |          0.307 |        48,099.022 |   82.749 |   15.897 |
| harmonic_residual_100   |    560 |          0.294 |        46,817.338 |   84.203 |   15.473 |
| history_shrinkage_25    |    560 |          0.252 |        47,185.906 |   43.612 |   15.595 |
| history_shrinkage_50    |    560 |          0.228 |        40,613.671 |   47.873 |   13.423 |
| adaptive_revenue_0      |    560 |          0.265 |        42,533.353 |   65.322 |   14.057 |
| adaptive_revenue_5      |    560 |          0.265 |        42,533.353 |   65.322 |   14.057 |
| adaptive_revenue_10     |    560 |          0.265 |        42,533.353 |   65.322 |   14.057 |
| adaptive_revenue_15     |    560 |          0.265 |        42,533.353 |   65.322 |   14.057 |

| Selected-model sector | Cases | Months | Normalized MAE | MAE (million UZS) | MAPE (%) |
| --------------------- | ----: | -----: | -------------: | ----------------: | -------: |
| accommodation_food    |    26 |    208 |          0.445 |         3,245.835 |  146.287 |
| market_services       |    40 |    320 |          0.156 |        27,640.339 |   18.718 |
| retail                |     3 |     24 |          0.188 |       501,940.757 |   14.734 |
| wholesale             |     1 |      8 |          0.161 |       281,507.200 |   16.614 |

MAPE excludes **4 zero-actual months**. Near-zero positive values remain included, so percentage errors can be large even when aggregate WAPE improves.

## Service transfer and limits

Raw MAE is dominated by large regions; normalized errors, percentage metrics and all sector slices are shown above. Three-month post-break histories, near-zero actuals and provider revisions can produce large errors, especially for food services. These previously examined benchmark results are regression evidence; the external-provider final audit supplies the new accuracy check.

The real revenue model and borrower expense projection form a net-flow candidate. Expenses use either a separately synthetic-trained model or a nonnegative cost regression fitted to the borrower's observed past transactions; public revenue supplies no expense labels. Fixed weights 0/0.1/0.25/0.5/1 are compared on the 60 synthetic validation businesses with normalized-error checks; selected real-component weight: **0.65**. Validation MAEs (indices): `{0.0: 106.08934572353616, 0.1: 104.5454814140975, 0.25: 102.84725222973175, 0.5: 101.4058637630507, 0.6: 101.20460796476301, 0.65: 101.23219400669332, 0.75: 101.50121565790191, 1.0: 103.23342660649178}`. Serving mode: `real_revenue_observed_costs_blend`. A zero weight rejects unsuitable transfer. [Synthetic borrower regression evaluation](metrics.md) measures the actual serving model.

MAE in declared million UZS is for real aggregates only; normalized MAE divides each window by its positive historical mean so districts, regions and sectors share a scale. MAPE excludes zero actuals and is unstable near zero; neither test metric selects the model.

A single current provider vintage may revise older observations. Target-date boundaries are enforced, but this is not a backtest with historical unrevised vintages. The service definition changed in September 2024; only October 2024 onward is used, excluding the incomparable September increment.

Original retail turnover and service value are aggregate revenue proxies, not independent firm cash receipts. Native currency units remain separate and only dimensionless errors are pooled. Survey revisions, correlated economic shocks, Uzbekistan short post-methodology histories, and cross-country aggregate-to-borrower transfer limit claims. No real costs, defaults or repayments are supplied.

All source data below are published by Uzbekistan's National Statistics Committee under **CC BY 4.0**. The committed snapshot declares raw source hashes, retrieval and modification dates, official units and methodology notes. Monthly increments difference year-to-date totals within each year; January resets. Published service billions are explicitly multiplied by 1000 to obtain million UZS in this benchmark. Borrower inference normalizes patterns and rescales by the supplied amount-index mean; this does **not** declare an index-to-UZS conversion.

- [Retail trade volume (by month)](https://siat.stat.uz/data/2699/?lang=en) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); provider units: million sums (UZS).
- [Wholesale trade volume (by month)](https://siat.stat.uz/data/964/?lang=en) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); provider units: million sums.
- [Volume of market services rendered (monthly, by districts and cities)](https://siat.stat.uz/data/3409/?lang=en) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); provider units: in bln. Soums.
- [Volume of accommodation and food services (monthly)](https://siat.stat.uz/data/3227/?lang=en) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); provider units: in bln. Soums.

Actual licensed revenue/service volume; no real borrower expenses, capacity, repayment or default labels. The original 2020–22/2023/2024–25 retail temporal benchmark remains separate and unchanged.

[Machine-readable report](revenue-metrics.json)
