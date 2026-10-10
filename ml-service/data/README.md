# Licensed public revenue datasets

The National Statistics Committee of the Republic of Uzbekistan publishes
[SIAT indicator 1.07.02.0002](https://siat.stat.uz/data/2699/?lang=en),
“Retail trade volume (by month),” under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The local snapshot contains its English regional labels and numeric observations,
with source URL, release date, raw download SHA-256, and retrieval date.
The dataset covers January 2020–August 2026, with 14 regional series and a national
total. These are public aggregate sales figures and contain no customer records.

The published values are year-to-date totals in million UZS. For example,
August 2026's national value corresponds to the officially reported
[January–August total of approximately UZS 370.6 trillion](https://stat.uz/en/press-center/news-of-committee/70489-chakana-savdo-tovar-ajlanmasi-azhmi-370-trln-s-mdan-oshdi-4).
The importer differences consecutive values **within each year**, and January
starts a new accumulation. It preserves the original totals alongside each
derived monthly increment. Fergana November 2023 has a negative increment in the
provider's published sequence. It remains recorded as a quality issue; affected
forecast cases are excluded without clipping or invented replacements.

`retail-calibration.json` uses only 2020–2022. Each complete, positive regional
year is normalized by its own monthly mean. The calendar-month median over 42
region-years is then normalized to mean one. The national total is excluded to
avoid counting the same activity twice. The synthetic generator mixes this
observed seasonality with simulated business variation, independent expenses,
noise, shocks, and hard cases. Its borrower flows remain synthetic.

The separate public forecast benchmark trains on actual 2020–2022 retail values,
selects a model using 2023, and evaluates 2024–2025. Regions recur across periods;
this is a temporal split. It measures aggregate revenue forecasting, and provides
no borrower expense, affordability, repayment, or default labels.

Refresh explicitly from the service directory:

```bash
uv run python scripts/import_public_data.py
cd ..
pnpm exec prettier --write ml-service/data/*.json
cd ml-service
```

Downloading is a development action. Training and inference read the committed
snapshot locally. A refresh changes the source digest and requires retraining
and regenerating the evaluation reports before starting the API.

## International original retail revenue

Two additional providers supply actual monthly sales, with no borrower costs,
repayment outcomes or personal customer records:

- [Australian Bureau of Statistics, Retail Trade June 2025, Table 11](https://www.abs.gov.au/statistics/industry/retail-and-wholesale-trade/retail-trade-australia/jun-2025):
  original state × industry subgroup turnover, **million AUD**, under
  [CC BY 4.0](https://www.abs.gov.au/website-privacy-copyright-and-disclaimer).
  The snapshot preserves 120 leaf series and 28,800 calendar points for
  July 2005–June 2025. June 2025 is the final release; this is historical data.
- [Statistics Canada, Table 20-10-0056-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2010005601):
  unadjusted total retail sales by province/territory and leaf NAICS category,
  **thousand CAD**, under the
  [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence).
  The snapshot preserves 260 series and 29,900 calendar points for
  January 2017–July 2026. The importer caps histories at 240 months; this
  table's published coverage is shorter.

Calendar coverage includes explicit null observations for suppressed, missing
or unreliable sales. It is not the count of actual numeric sales records.
The international snapshots contain **49,213 numeric published observations**
and **9,487 null entries**. Training uses 32,484 overlapping future-month targets,
corresponding to 17,232 unique source target observations; the remaining values
include input histories, validation and reserved final periods.
Parent/national totals and overlapping categories are excluded. Original
monthly flow values are used; seasonally adjusted series and e-commerce
duplicates are excluded. No currency conversion or gap-zero imputation occurs.
The snapshots record source URLs, units, license, attribution, raw SHA-256,
retrieval date and frozen split protocol. Adaptations imply no provider endorsement.

Each provider's geographic groups are sorted by a fixed SHA-256 seed and split
into training, validation and final audit groups. All industries in a state or
province stay together. Training targets end in June 2023 (Australia) or July
2024 (Canada). Validation uses the next 12 months; the reserved final audit uses
July 2024–June 2025 or August 2025–July 2026. Final cases are constructed only
by the evaluator after model selection is fixed. Time boundaries are local to
each provider; later training labels from another country can overlap a test
date, so this is not a globally chronological backtest. Current revision
vintages and common economic shocks also limit independence.

Refresh explicitly with `uv run python scripts/import_international_data.py`.
The importer bounds downloads and archive expansion, checks source units and
original monthly metadata, preserves quality gaps and writes snapshots
atomically. Training and serving read committed snapshots offline. Format JSON
with Prettier before retraining because exact snapshot bytes enter the artifact
digest. A data refresh consumes the original final audit; review the protocol
and report that status rather than repeatedly calling tuned tests fresh.
