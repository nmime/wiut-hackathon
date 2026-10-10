# Uzbekistan public-revenue regression benchmark

Measured 2026-10-10T19:30:46.077792+00:00; artifact `local-v3-90057d5d69d7-gradient_boosting-public10`. Reproduce with `uv run python -m capacity_ml.train` and `uv run python -m capacity_ml.evaluate_revenue`.

These fixed Uzbekistan evaluation periods were reported before this model upgrade. They are now **legacy regression benchmarks**, not fresh confirmatory holdouts. Targets remain excluded from fitting and validation selection. See the [new international evaluation](international-metrics.md) for separately reserved final-period observations.

The offline corpus contains **16,544 published monthly observations** across retail, wholesale, district market services and accommodation/food service aggregates. Excluding national and parent totals, then respecting the service methodology boundary, leaves **440 eligible series / 11,716 observations**. These counts include retained source revisions; invalid forecasting windows are excluded rather than corrected or clipped.

The Uzbekistan portion supplies **740 rolling windows / 8,880 actual target-month examples** from **187 series**, representing **2,797 unique target observations**. The combined Uzbekistan/Australia/Canada model uses **41,364 actual target examples**; overlapping windows are not independent records. Uzbekistan targets end by December 2025. Regions are partitioned by a fixed hash into 8 training, 3 validation and 3 legacy test groups; all sectors/districts of a region stay together. Pre-2025 retail/wholesale histories are capped at 48 months. Post-break service histories before January 2025 contain only 3 months and are a cold-history limitation.

Uzbekistan development validation covers January–December 2025 in independent geographic groups. The combined model selects **history_shrinkage_50** by provider-balanced macro normalized validation MAE, giving each provider equal weight. The table below shows only the Uzbekistan validation slice, which may prefer a different candidate. Test targets remain excluded from fitting and selection. Source-revision exclusions: `{'train': 274, 'validation': 66, 'test_2025': 26, 'test_2026': 26}`. The 2025 legacy evaluation is an entity holdout; the 2026 evaluation also follows Uzbekistan training in time. Only January–August 2026 is published: the last four forecast months are unobserved and excluded.

Valid-window composition: `{'train': {'accommodation_food': 80, 'market_services': 91, 'retail': 366, 'wholesale': 203}, 'validation': {'accommodation_food': 11, 'market_services': 18, 'retail': 3, 'wholesale': 0}, 'test_2025': {'accommodation_food': 27, 'market_services': 40, 'retail': 3, 'wholesale': 0}, 'test_2026': {'accommodation_food': 26, 'market_services': 40, 'retail': 3, 'wholesale': 1}}`. In particular, source revisions exclude wholesale from validation and the 2025 holdout; its one 2026 case cannot establish sector-wide performance. The geographic validation group is small and uneven after exclusions.

| Candidate               | Validation normalized MAE | Validation MAE (million UZS) | Validation MAPE (%) |
| ----------------------- | ------------------------: | ---------------------------: | ------------------: |
| seasonal_naive          |                     0.247 |                   53,893.364 |              52.622 |
| trend_adjusted_seasonal |                     0.241 |                   45,408.211 |              52.428 |
| damped_seasonal         |                     0.239 |                   39,231.440 |              52.081 |
| robust_harmonic         |                     0.258 |                   58,816.725 |              53.273 |
| gradient_boosting       |                     0.150 |                   36,808.146 |              40.361 |
| learned_residual        |                     0.150 |                   37,097.145 |              39.457 |
| residual_blend_25       |                     0.205 |                   36,787.145 |              47.873 |
| residual_blend_50       |                     0.175 |                   35,542.267 |              43.929 |
| harmonic_residual_25    |                     0.222 |                   51,861.231 |              48.923 |
| harmonic_residual_50    |                     0.187 |                   45,425.653 |              44.761 |
| history_shrinkage_25    |                     0.148 |                   34,438.160 |              39.396 |
| history_shrinkage_50    |                     0.148 |                   34,758.639 |              39.396 |

## test 2025

Valid series: 70; excluded complete windows: 26. Candidates below are reported after validation selection is fixed.

| Candidate               | Months | Normalized MAE | MAE (million UZS) | MAPE (%) | WAPE (%) |
| ----------------------- | -----: | -------------: | ----------------: | -------: | -------: |
| seasonal_naive          |    840 |          1.402 |        46,121.144 |   61.138 |   19.197 |
| trend_adjusted_seasonal |    840 |          1.398 |        38,396.802 |   60.976 |   15.982 |
| damped_seasonal         |    840 |          1.398 |        37,920.584 |   60.914 |   15.784 |
| robust_harmonic         |    840 |          1.416 |        48,775.042 |   60.594 |   20.302 |
| gradient_boosting       |    840 |          1.356 |        31,087.099 |   53.791 |   12.940 |
| learned_residual        |    840 |          1.359 |        31,545.290 |   54.390 |   13.130 |
| residual_blend_25       |    840 |          1.376 |        34,949.928 |   58.026 |   14.547 |
| residual_blend_50       |    840 |          1.359 |        32,400.948 |   55.613 |   13.486 |
| harmonic_residual_25    |    840 |          1.388 |        42,899.055 |   57.704 |   17.856 |
| harmonic_residual_50    |    840 |          1.366 |        37,468.207 |   55.323 |   15.596 |
| history_shrinkage_25    |    840 |          1.359 |        30,454.810 |   54.373 |   12.676 |
| history_shrinkage_50    |    840 |          1.359 |        30,737.514 |   54.376 |   12.794 |

| Selected-model sector | Cases | Months | Normalized MAE | MAE (million UZS) | MAPE (%) |
| --------------------- | ----: | -----: | -------------: | ----------------: | -------: |
| accommodation_food    |    27 |    324 |          3.247 |         3,472.864 |  107.665 |
| market_services       |    40 |    480 |          0.176 |        27,127.960 |   22.106 |
| retail                |     3 |     36 |          0.142 |       324,246.754 |   12.438 |

MAPE excludes **5 zero-actual months**. Near-zero positive values remain included, so percentage errors can be large even when aggregate WAPE improves.

## test 2026

Valid series: 70; excluded complete windows: 26. Candidates below are reported after validation selection is fixed.

| Candidate               | Months | Normalized MAE | MAE (million UZS) | MAPE (%) | WAPE (%) |
| ----------------------- | -----: | -------------: | ----------------: | -------: | -------: |
| seasonal_naive          |    560 |          0.312 |        66,544.133 |   44.502 |   21.993 |
| trend_adjusted_seasonal |    560 |          0.307 |        53,636.825 |   44.103 |   17.727 |
| damped_seasonal         |    560 |          0.309 |        58,503.008 |   44.245 |   19.336 |
| robust_harmonic         |    560 |          0.365 |        56,749.751 |   85.064 |   18.756 |
| gradient_boosting       |    560 |          0.283 |        44,366.795 |   84.581 |   14.663 |
| learned_residual        |    560 |          0.273 |        45,799.316 |   66.362 |   15.137 |
| residual_blend_25       |    560 |          0.282 |        51,511.165 |   47.121 |   17.025 |
| residual_blend_50       |    560 |          0.269 |        47,316.778 |   52.319 |   15.638 |
| harmonic_residual_25    |    560 |          0.330 |        50,894.944 |   79.120 |   16.821 |
| harmonic_residual_50    |    560 |          0.301 |        46,348.114 |   73.733 |   15.318 |
| history_shrinkage_25    |    560 |          0.282 |        51,511.165 |   47.121 |   17.025 |
| history_shrinkage_50    |    560 |          0.269 |        47,316.778 |   52.319 |   15.638 |

| Selected-model sector | Cases | Months | Normalized MAE | MAE (million UZS) | MAPE (%) |
| --------------------- | ----: | -----: | -------------: | ----------------: | -------: |
| accommodation_food    |    26 |    208 |          0.451 |         3,665.731 |  117.322 |
| market_services       |    40 |    320 |          0.158 |        31,427.617 |   14.535 |
| retail                |     3 |     24 |          0.199 |       545,623.238 |   15.168 |
| wholesale             |     1 |      8 |          0.185 |       322,891.062 |   17.566 |

MAPE excludes **4 zero-actual months**. Near-zero positive values remain included, so percentage errors can be large even when aggregate WAPE improves.

## Service transfer and limits

Raw MAE is dominated by large regions; normalized errors, percentage metrics and all sector slices are shown above. Three-month post-break histories, near-zero actuals and provider revisions can produce large errors, especially for food services. These previously examined benchmark results are regression evidence; the separate international final audit supplies the new accuracy check.

The real revenue model and borrower expense projection form a net-flow candidate. Expenses use either a separately synthetic-trained model or a nonnegative cost regression fitted to the borrower's observed past transactions; public revenue supplies no expense labels. Fixed weights 0/0.1/0.25/0.5/1 are compared on the 60 synthetic validation businesses with normalized-error checks; selected real-component weight: **0.1**. Validation MAEs (indices): `{0.0: 106.08934572353616, 0.1: 105.64676777063806, 0.25: 105.77294237569284, 0.5: 108.4728886031166, 1.0: 120.79993965202344}`. Serving mode: `real_revenue_observed_costs_blend`. A zero weight rejects unsuitable transfer. [Synthetic borrower regression evaluation](metrics.md) measures the actual serving model.

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
