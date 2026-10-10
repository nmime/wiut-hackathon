# Public Uzbekistan retail revenue benchmark

Measured 2026-10-10T20:52:12.151303+00:00. This benchmark trains a separate revenue forecaster on actual public monthly retail turnover. It does not measure borrower payment capacity or repayment performance.

Source: [National Statistics Committee of the Republic of Uzbekistan](https://siat.stat.uz/data/2699/?lang=en), indicator 1.07.02.0002; [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Published year-to-date totals become monthly increments by within-year differences and a January reset. Units remain **million UZS**.

Train on 2020–2022 only, choose once by pooled 2023 validation MAE, and evaluate fixed parameters/candidate on 2024 and 2025. Regions repeat across years, so this is a **temporal holdout**, not an entity-disjoint test. Each January forecast uses history observed before that year; 2025 may use actual 2024 history without retraining. The national total is excluded to avoid duplicating regional observations. 2026 is unused.

Training: 14 regions, 182 rolling origins and 2184 horizon examples. Twelve-month targets end no later than 2022-12; overlapping training targets are not independent evaluation samples. Fixed seed 20261010; boosting parameters are listed in the JSON report.

Validation selected **trend_adjusted_seasonal**. All candidates remain visible below; test performance does not change selection. MAE weights absolute revenue errors and therefore favors larger regions. MAPE uses actual>0 observations only; zero denominators are counted separately.

| Split              | Candidate               | Regions / cases | Months | MAE (million UZS) | MAPE (%) | MAPE included / excluded |
| ------------------ | ----------------------- | --------------: | -----: | ----------------: | -------: | -----------------------: |
| Validation 2023    | seasonal_naive          |         13 / 13 |    156 |         450376.62 |    25.62 |                  156 / 0 |
| Validation 2023    | trend_adjusted_seasonal |         13 / 13 |    156 |         368852.54 |    22.94 |                  156 / 0 |
| Validation 2023    | gradient_boosting       |         13 / 13 |    156 |         425887.50 |    24.53 |                  156 / 0 |
| Held-out 2024–2025 | seasonal_naive          |         13 / 26 |    312 |         571656.93 |    23.74 |                  312 / 0 |
| Held-out 2024–2025 | trend_adjusted_seasonal |         13 / 26 |    312 |         405882.00 |    18.99 |                  312 / 0 |
| Held-out 2024–2025 | gradient_boosting       |         13 / 26 |    312 |         440180.77 |    18.31 |                  312 / 0 |
| Held-out 2024      | seasonal_naive          |         13 / 13 |    156 |         540855.61 |    23.47 |                  156 / 0 |
| Held-out 2024      | trend_adjusted_seasonal |         13 / 13 |    156 |         381456.34 |    16.41 |                  156 / 0 |
| Held-out 2024      | gradient_boosting       |         13 / 13 |    156 |         433614.05 |    17.15 |                  156 / 0 |
| Held-out 2025      | seasonal_naive          |         13 / 13 |    156 |         602458.25 |    24.02 |                  156 / 0 |
| Held-out 2025      | trend_adjusted_seasonal |         13 / 13 |    156 |         430307.66 |    21.57 |                  156 / 0 |
| Held-out 2025      | gradient_boosting       |         13 / 13 |    156 |         446747.50 |    19.47 |                  156 / 0 |

Seasonal naive repeats the same calendar month from the previous year. Trend-adjusted seasonal multiplies it by the latest annual turnover growth ratio. Gradient boosting uses the existing lag/calendar feature helpers with revenue as a single series and a neutral subtraction array; this is not expense data. This in-memory model never replaces the synthetic `/score` model.

Excluded 3 region-origin cases due to invalid or missing source increments; no clipping, imputation, or invented labels. The current snapshot's negative Fergana 2023-11 increment invalidates its 2023 target and subsequent full-history forecasts in 2024 and 2025. Exact exclusion records and all evaluated histories are in the JSON report.

Limitations:

- Regions repeat across years. This is a temporal regional revenue benchmark, not an unseen-business test; the separate synthetic evaluation is business-disjoint.
- Current published snapshot may contain historical revisions. Release-vintage data are unavailable, so this is not a fully vintage-correct historical backtest.
- Turnover is nominal aggregate revenue in published million UZS, without expenses, inflation adjustment, borrower balances, payment outcomes, or default labels.
- Only 13 valid regional cases per evaluation year remain in this snapshot. Growth, reporting changes and regional aggregation limit transfer to individual businesses.
- Public benchmark results do not validate the capacity heuristic, its confidence, or adaptive repayment safety. No bank production-performance claim is made.

Reproduce offline from the committed source snapshot:

```sh
cd ml-service
uv run python -m capacity_ml.evaluate_public
```
