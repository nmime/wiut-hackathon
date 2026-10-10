# Local payment capacity service

This optional FastAPI module forecasts synthetic business net cash flow and calculates an explainable payment capacity recommendation. It does not predict default or approve credit. NestJS persists the assessment and every human officer decision; the Python service also maintains a durable local audit for direct `/score` calls.

## Reproduce, test and run

Python 3.12 and uv 0.11.28 are used. Direct and transitive dependencies are pinned in `pyproject.toml` and `uv.lock`. From this directory:

```sh
uv sync --frozen
uv run python -m capacity_ml.train
uv run python -m capacity_ml.evaluate
uv run python -m capacity_ml.evaluate_public
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run uvicorn capacity_ml.api:app --host 127.0.0.1 --port 8000
```

`GET /health` reports the loaded model version. `POST /score` follows [the shared contract](../docs/ml-integration.md); interactive schema documentation is at `/docs`. NestJS uses `ML_SERVICE_URL=http://127.0.0.1:8000` locally or `http://ml:8000` in Compose.

`ML_MODEL_PATH` defaults to `runtime/model.joblib`; `ML_AUDIT_PATH` defaults to `runtime/audit.jsonl`. These files are ignored. Training explicitly regenerates a compact artifact; startup fails if it is absent, corrupt or stale relative to generator, features, training or scoring code. There is no hardcoded recommendation fallback. Only load artifacts built from trusted local source: joblib deserialization can execute Python code.

The Dockerfile installs the frozen environment and trains during the build, then serves on port 8000 as uid/gid 10001. The trained artifact is read-only; `/data/audit` is writable. From the repository root, the optional Compose configuration is `docker compose -f docker-compose.yml -f docker-compose.ml.yml up --build`. Public deployment has not been performed; a public demonstration must use only synthetic business inputs. Production scoring requires a private bank network, access control and a durable audit volume.

## Data and forecasting

Business profiles, inflows, outflows and transaction events are synthetic. The fixed seed is **20261010**; [generator.py](capacity_ml/generator.py) contains the full process. Revenue is base × calendar seasonality × time trend × multiplicative noise, with correlated shocks. Expenses combine a stochastic revenue share and independent operating costs. Positive transaction sizes use a Dirichlet allocation; event dates and card/transfer/QR/cash/other channels are sampled. There are no confidential records, customer identifiers, invented default labels or borrowed elimination-stage implementation.

The population includes stable, seasonal, growing, declining, volatile growing, cold-start and negative-surplus businesses, plus abrupt seasonal/level changes. Test-only unfamiliar seasonal shapes and realised shocks prevent trivial reconstruction. The model cannot see latent parameters or cohort labels. The future actual transaction process, rather than a score-generation formula, is the evaluation target.

The seasonal, growing, declining and volatile growing cohorts blend 50% of their calendar component with **official Uzbekistan SIAT retail seasonality derived only from 2020–2022**. The source is [retail trade volume, indicator 1.07.02.0002](https://siat.stat.uz/data/2699/?lang=en), published by Uzbekistan's National Statistics Committee under CC BY 4.0. [The offline snapshot](data/uzbekistan-retail.json), [calibration](data/retail-calibration.json) and [import script](scripts/import_public_data.py) declare provenance, license and transformation. Monthly regional revenue increments are differences of year-to-date turnover within each year; January starts a new year. The snapshot retains a negative increment from source revision with a quality flag; that region-year is excluded from calibration/benchmark rather than clipped. Regional monthly factors are normalised by each annual mean, combined by calendar median and normalised to mean one; the national total is excluded. Public 2023+ values never calibrate the synthetic generator or select its model. They are retained for the separate [actual aggregate revenue benchmark](reports/public-metrics.md), which has no business expense, capacity or repayment labels. The public aggregates do not turn synthetic borrowers into real bank data.

Training uses 180 businesses and rolling historical cutoffs; complete and incomplete assessment-month variants are included. A separate 60-business validation set chooses between seasonal naive, gradient boosting and a 50/50 blend by future-12-month MAE. The model is not refit on validation/test businesses. The 120-business test set contributes 12 later actual months per business and never controls selection or score/schedule parameters.

The baseline takes the most recent observed net flow from the same calendar month; unseen calendar months use the observed historical mean. `HistGradientBoostingRegressor` forecasts normalised future net flow from lags 1/2/3/6/12, rolling means/volatility, observed trend, elapsed horizon, calendar sine/cosine, seasonal baseline, history length and inflow/outflow means. All inference is local. The positive last-12-month observed inflow mean normalises indices, with an outflow fallback only when inflows are zero, so changing the index scale changes monetary outputs proportionally and preserves the score.

Transactions are grouped by their supplied calendar date/month, including timestamps with offsets, consistent with NestJS. Calendar gaps count as zero flow. The incomplete assessment month is excluded whenever complete history exists; forecasts always begin the next calendar month after assessment. A partial-only history is retained for an illustrative forecast with confidence at most 0.03 and no loan. Requests accept at most 20,000 events, 240 calendar months through assessment and a 5 MiB body; calendar dates that overflow the next 12 months are rejected.

[Measured evaluation](reports/metrics.md) and [the JSON report](reports/metrics.json) include all forecasting candidates, partial-month evaluation, capacity coverage, equal-payment comparisons, seasonality precision, latency and failure cohorts. MAE is in amount indices. MAPE excludes absolute actual net flow below 1 index and can be misleading near zero or for negative surplus; it is not used to select the model. Timings are local sequential warm requests with audit fsync, not a network or concurrent-load benchmark.

## Capacity and repayment policy

Capacity is a transparent heuristic, not an ML classifier or probability of default. Before the viability gate, the score is a weighted 0–100 composition:

| Factor                   | Weight | Normalisation                                                   |
| ------------------------ | -----: | --------------------------------------------------------------- |
| Forecast surplus margin  |    35% | Median forecast / observed inflow scale / 0.5, clipped to 0–1   |
| Inflow stability         |    20% | 1 / (1 + 2 × inflow coefficient of variation)                   |
| Positive forecast months |    20% | Fraction of positive future forecasts                           |
| Observed surplus trend   |    10% | 0.5 + 12 × monthly net-flow slope / mean inflow, clipped to 0–1 |
| Months with inflow       |    15% | Fraction of historical calendar months with positive inflow     |

The viability gate requires at least six observed active months, positive historical surplus and inflow, and fewer than three stale complete months. It multiplies the score by the fraction of positive forecast months; inadequate evidence yields score/principal zero. Explanation `weight` values are signed score-point contributions around a baseline of 50 plus the gate adjustment, so they reconstruct the final score. The response trend describes observed **inflow**; the capacity trend factor separately uses **net surplus**.

Confidence is an uncalibrated evidence indicator: observed active history length up to 36 months, inflow volatility, recent activity coverage and recency reduce it. Short histories are capped at 0.25; observed abrupt inflow changes reduce it further. It is not a prediction interval or a success probability.

The capacity buffer is `0.55 / (1 + min(volatility, 2)) × (0.5 + 0.5 × confidence)`. Each month capacity is `max(predicted surplus, 0) × buffer`. The adaptive payment uses **85%** of that month capacity; indexed principal is the sum of the 12 payments. The displayed `max_affordable_installment_index` is the **20th percentile** of buffered capacities as a conservative equal-payment reference; adaptive monthly payments have their own caps and can be larger. Weak/strong months are calendar month numbers in the forecast bottom/top quartiles, with no overlapping ties. Payment notes compare each payment to the schedule mean.

**Interest is explicitly 0% in this MVP.** Total scheduled repayment equals indexed principal, each payment is nonnegative and capped by its buffered forecast-month capacity, and there is no negative amortisation. Evaluation compares the exact same principal, term and zero rate with equal installments, equivalent to a zero-interest annuity. Commercial interest, fees, amortisation, minimum instalments and contract pricing are outside this prototype and require a new declared policy and evaluation.

`requested_amount` is in UZS while all flows, principals and installments are **indices**. No index-to-UZS conversion is declared. A non-null requested amount therefore produces `currency_conversion_missing` and advice, and cannot numerically cap the indexed recommendation. No indexed result is labelled as currency.

## Audit and operational limits

Every `/score` attempt receives or preserves a safe `X-Request-Id` and appends a requested event plus completion/failure event to JSONL. Complete accepted bodies have a SHA-256 of their exact bytes; oversized bodies that are not fully consumed explicitly record prefix scope or a null hash. Success logs the full validated response, its hash, model version and timing before releasing the response. Transactions are not copied into audit entries. A failed audit append returns 503 and releases no recommendation. NestJS separately persists API attempts, full validated results and all final human decisions.

The audit lock is process-local: run one Uvicorn worker. This is not a replicated/tamper-evident ledger; retention, encryption, backups, crash recovery, rate limiting, authentication and multiworker coordination require production implementation. A crash between requested and completed events leaves an identifiable incomplete attempt. Inference calls no external API and has no per-request provider fee; CPU, storage and operations still have costs that this project has not monetarily measured.

Structural breaks, unexpected future expenses and unfamiliar seasonal patterns can defeat the forecast. Zero/negative surplus and sparse or stale histories suppress lending, while high volatility reduces confidence and buffered capacity. Neither score nor buffer guarantees future affordability. Synthetic coverage and aggregate data cannot establish real-client repayment performance. No final credit decision, bank integration, autonomous origination or public deployment is included.
