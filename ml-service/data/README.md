# Public retail dataset

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
