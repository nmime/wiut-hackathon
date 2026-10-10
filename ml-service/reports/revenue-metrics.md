# Direct public-revenue training and measured holdouts

Measured 2026-10-10T19:07:22.382672+00:00; artifact `local-v2-4965cd4bd648-gradient_boosting-public0`. Reproduce with `uv run python -m capacity_ml.train` and `uv run python -m capacity_ml.evaluate_revenue`.

The offline corpus contains **16,544 published monthly observations** across retail, wholesale, district market services and accommodation/food service aggregates. Excluding national and parent totals, then respecting the service methodology boundary, leaves **440 eligible series / 11,716 observations**. These counts include retained source revisions; invalid forecasting windows are excluded rather than corrected or clipped.

Direct real-data training uses **740 rolling windows / 8,880 actual future-month targets** from **187 series**, representing **2,797 unique target observations**. Overlapping rolling windows are not independent records. All training targets end by December 2025. Regions are partitioned by a fixed hash into 8 training, 3 validation and 3 test groups; all sector/district records from a region stay together. Pre-2025 retail/wholesale histories are capped at 48 months. Post-break service histories before January 2025 contain only 3 months and are explicitly a cold-history limitation.

Validation covers January–December 2025 in independent geographic groups. It selects **gradient_boosting** by historical-scale-normalized MAE. No test labels are read to fit or choose the candidate. Source-revision exclusions by split: `{'train': 274, 'validation': 66, 'test_2025': 26, 'test_2026': 26}`. The 2025 entity holdout is contemporaneous with training; the 2026 test is both geographic and future-time holdout. Only January–August 2026 is published: the last four forecast months are unobserved and excluded from metrics.

Valid-window composition: `{'train': {'accommodation_food': 80, 'market_services': 91, 'retail': 366, 'wholesale': 203}, 'validation': {'accommodation_food': 11, 'market_services': 18, 'retail': 3, 'wholesale': 0}, 'test_2025': {'accommodation_food': 27, 'market_services': 40, 'retail': 3, 'wholesale': 0}, 'test_2026': {'accommodation_food': 26, 'market_services': 40, 'retail': 3, 'wholesale': 1}}`. In particular, source revisions exclude wholesale from validation and the 2025 holdout; its one 2026 case cannot establish sector-wide performance. The geographic validation group is small and uneven after exclusions.

| Candidate               | Validation normalized MAE | Validation MAE (million UZS) | Validation MAPE (%) |
| ----------------------- | ------------------------: | ---------------------------: | ------------------: |
| seasonal_naive          |                     0.247 |                   53,893.364 |              52.622 |
| trend_adjusted_seasonal |                     0.241 |                   45,408.211 |              52.428 |
| gradient_boosting       |                     0.148 |                   36,581.403 |              40.674 |

## test 2025

Valid series: 70; excluded complete windows: 26. Candidates below are reported after validation selection is fixed.

| Candidate               | Months | Normalized MAE | MAE (million UZS) | MAPE (%) | WAPE (%) |
| ----------------------- | -----: | -------------: | ----------------: | -------: | -------: |
| seasonal_naive          |    840 |          1.402 |        46,121.144 |   61.138 |   19.197 |
| trend_adjusted_seasonal |    840 |          1.398 |        38,396.802 |   60.976 |   15.982 |
| gradient_boosting       |    840 |          1.365 |        31,200.168 |   55.888 |   12.987 |

| Selected-model sector | Cases | Months | Normalized MAE | MAE (million UZS) | MAPE (%) |
| --------------------- | ----: | -----: | -------------: | ----------------: | -------: |
| accommodation_food    |    27 |    324 |          3.241 |         3,534.606 |  108.995 |
| market_services       |    40 |    480 |          0.192 |        29,148.896 |   23.834 |
| retail                |     3 |     36 |          0.133 |       307,540.520 |   12.677 |

MAPE excludes **5 zero-actual months**. Near-zero positive values remain included, so percentage errors can be large even when aggregate WAPE improves.

## test 2026

Valid series: 70; excluded complete windows: 26. Candidates below are reported after validation selection is fixed.

| Candidate               | Months | Normalized MAE | MAE (million UZS) | MAPE (%) | WAPE (%) |
| ----------------------- | -----: | -------------: | ----------------: | -------: | -------: |
| seasonal_naive          |    560 |          0.312 |        66,544.133 |   44.502 |   21.993 |
| trend_adjusted_seasonal |    560 |          0.307 |        53,636.825 |   44.103 |   17.727 |
| gradient_boosting       |    560 |          0.265 |        40,206.305 |   96.916 |   13.288 |

| Selected-model sector | Cases | Months | Normalized MAE | MAE (million UZS) | MAPE (%) |
| --------------------- | ----: | -----: | -------------: | ----------------: | -------: |
| accommodation_food    |    26 |    208 |          0.461 |         2,861.473 |  229.748 |
| market_services       |    40 |    320 |          0.146 |        24,703.655 |   20.330 |
| retail                |     3 |     24 |          0.170 |       456,210.600 |   13.388 |
| wholesale             |     1 |      8 |          0.219 |       383,265.072 |   23.743 |

MAPE excludes **4 zero-actual months**. Near-zero positive values remain included, so percentage errors can be large even when aggregate WAPE improves.

## Service transfer and limits

The selected model improves pooled MAE on both holdouts, but its 2026 **MAPE is worse than both seasonal baselines**, and accommodation/food forecasts have especially large percentage errors. Raw MAE is dominated by large regions; normalized metrics and sector failures are shown to prevent a broad accuracy claim. Three-month post-break histories and source revisions limit the 2025 service evaluation. No test-driven retuning was performed.

The trained real revenue model is stored in the same artifact as a separately synthetic-trained expense model. Their difference is a transferable net-flow candidate. Fixed blend weights 0/0.25/0.5/1 are compared only on the 60 synthetic validation businesses; selected real-component weight: **0.0**. Validation MAEs (indices): `{0.0: 106.08934572353618, 0.25: 116.33652057233715, 0.5: 145.27149147616544, 1.0: 223.2874668724231}`. Serving mode: `synthetic_net_public_transfer_rejected`. A zero weight explicitly rejects transfer and retains the synthetic forecast; it is not a fabricated output fallback. [Synthetic borrower/capacity evaluation](metrics.md) measures the actual selected serving model.

MAE in declared million UZS is for real aggregates only; normalized MAE divides each window by its positive historical mean so districts, regions and sectors share a scale. MAPE excludes zero actuals and is unstable near zero; neither test metric selects the model.

A single current provider vintage may revise older observations. Target-date boundaries are enforced, but this is not a backtest with historical unrevised vintages. The service definition changed in September 2024; only October 2024 onward is used, excluding the incomparable September increment.

Aggregate service value/turnover is a proxy for revenue, not bank cash receipts. Preliminary single-vintage revisions, COVID-era trade observations, three-month post-break service histories and overlapping service categories limit transfer claims. Geographic partitions keep all categories and parent/child observations of a region together.

All source data below are published by Uzbekistan's National Statistics Committee under **CC BY 4.0**. The committed snapshot declares raw source hashes, retrieval and modification dates, official units and methodology notes. Monthly increments difference year-to-date totals within each year; January resets. Published service billions are explicitly multiplied by 1000 to obtain million UZS in this benchmark. Borrower inference normalizes patterns and rescales by the supplied amount-index mean; this does **not** declare an index-to-UZS conversion.

- [Retail trade volume (by month)](https://siat.stat.uz/data/2699/?lang=en) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); provider units: million sums (UZS).
- [Wholesale trade volume (by month)](https://siat.stat.uz/data/964/?lang=en) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); provider units: million sums.
- [Volume of market services rendered (monthly, by districts and cities)](https://siat.stat.uz/data/3409/?lang=en) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); provider units: in bln. Soums.
- [Volume of accommodation and food services (monthly)](https://siat.stat.uz/data/3227/?lang=en) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); provider units: in bln. Soums.

Actual licensed revenue/service volume; no real borrower expenses, capacity, repayment or default labels. The original 2020–22/2023/2024–25 retail temporal benchmark remains separate and unchanged.

[Machine-readable report](revenue-metrics.json)
