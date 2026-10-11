# FlowCredit · WIUT Hackathon

An independent hackathon prototype for bank and credit teams. No bank or regulator
affiliation, partnership or endorsement is claimed.

FlowCredit helps an officer import a business's transactions, inspect cash flow, and review an
explainable payment-capacity recommendation with a seasonal repayment plan.
A human records the final decision; the score is **payment capacity, not default probability**.

- [Public prototype](https://wiut-hackathon.dehqonhub.uz)
- [Public repository](https://github.com/nmime/wiut-hackathon)
- [Release readiness and verification](docs/release-readiness.md)
- [Data sources, licences and attribution](docs/data-sources.md)

## One application, one served model

The product has one React/Vite frontend, one NestJS/Fastify API, PostgreSQL, and
one local Python `/score` service. The final scorer combines the frozen
real-trained revenue forecast, intervals calibrated on real revenue residuals,
the business's observed costs, and verified seasonal amortization primitives.
It offers **24% nominal annual interest**, a twelve-month plan, and three advisory
verdicts: **affordable / elevated risk — officer review / decline**. Affordability
uses the seasonal schedule actually offered. Principal, interest and total
payments reconcile. Requested principal is checked against that capacity.

Production serves `final_model.api:app` from `hybrid-runtime`; the frontend has
no model selector. Selected frozen forecast and financial modules are dependencies
of the final scorer. Historical service entry points, artifacts and reports remain
for reproducible research and regression evidence; they are not separately served.
The [final runtime](docs/final-model-runtime.md) describes the component hashes,
policy and audit. Inference makes **no external API calls**.

## Run the complete stack

Install Docker with Compose. From a clean checkout:

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.ml.yml up --build -d
```

Open **http://localhost:8080**. The API is proxied at `/api`, with Swagger at
`/api/docs`. Images load the committed, verified final model; builds do not
retrain it. Database and ML audit data live in named volumes. Local published
ports bind to loopback. See [production deployment](docs/deployment.md) for HTTPS,
private service networking, backups and persistent encryption keys.

Create an account and a bank/team workspace. New bank workspaces start **empty**.
Import an actual business's UZS CSV or JSON, or open **Showcase lab** and explicitly
create a separate workspace for disclosed synthetic scenarios. Showcase businesses
never enter the bank portfolio. The jury can generate another scenario, change
the inputs, analyze it, record an officer decision, and inspect its audit.
See [imports](docs/imports.md) and [Showcase lab](docs/showcase.md).

## Develop locally

Use **Node 24, pnpm 12.8.1, Python 3.12 and uv**. PostgreSQL is required.

```bash
corepack enable
pnpm install --frozen-lockfile
cp .env.example .env
pnpm db:up
uv sync --frozen --directory hybrid-runtime
./scripts/serve_final_model.sh
```

In another terminal, set `ML_SERVICE_URL=http://127.0.0.1:8110` in `.env`, then:

```bash
pnpm dev
```

Open **http://localhost:5173**. Nest listens on `127.0.0.1:3000`; PostgreSQL on
`127.0.0.1:55432`. If ML is disconnected, imports and history work, and analysis
records an explicit failed attempt. It never substitutes a fabricated result.
For MFA, generate `AUTH_ENCRYPTION_KEY` with `openssl rand -hex 32` and preserve
that ignored value across restarts and backups.

## Officer workflow

1. Sign in, select a workspace, and import transactions in **UZS**.
2. Review history and provenance. Choose a cutoff date and optional requested sum.
3. Analyze and inspect the verdict, capacity score, evidence confidence, warnings,
   forecast and seasonal payments, including interest and total repayment.
4. Record approval, decline, or a request for information with reasoning.
5. Inspect assessment history and audit events; export transactions or the result.

Every accepted analysis attempt, including failures, is persisted. Decisions
retain the authenticated officer's identity and are immutable; reassess for a
new review. Input and ML output are validated through shared Zod/Pydantic schemas.
For actual imports, **1 internal amount unit = 1 UZS**. Historical indexed records
retain their original unit and are not relabelled as currency.

Administrators invite members through **Team & access**. Links are email-bound,
revocable and expire after seven days; the application does not send email.
Accounts support optional authenticator MFA, backup codes and an offline recovery
key. Workspace switching rotates CSRF state and clears the query cache. Queries
and review permissions are tenant scoped. See [account security](docs/account-security.md)
and [operations](docs/operations.md).

## Why this final model

The revenue component was compared on licensed, real public time series. A new
LightGBM blend reduced fresh normalized revenue error by **2.181%** on
**454 twelve-month windows / 5,448 monthly targets**. It missed the preregistered
**5%** promotion requirement, so the frozen incumbent remains the forecast default.
Its error was **0.099779**, versus **0.097602** for the research blend and
**0.121036** for seasonal naive. These are dimensionless revenue errors, not loan
repayment or default metrics. New training is not attributed to the frozen model.

The final financial layer improves functionality: interest-bearing seasonal
capacity, requested-amount checks, a sustained-decline guard, and three verdicts.
A positive median is not declined solely because its lower revenue band is wide.
Automatic offers below 5% of their tier's discounted payment budget are rejected
before trying the next tier, preventing numerical micro-offers from receiving
an affordable verdict. The engine exposes the evidence and leaves the decision
to the officer.

Evidence is retained, including failed candidates and adverse results:

- [Fresh real-data selection, held-out predictions and interval coverage](ml-service/reports/revenue-upgrade-fresh.md)
- [Earlier common real-data model comparison](ml-service/reports/real-model-benchmark.md)
- [Financial accounting and schedule behaviour checks](ml-service/reports/final-financial-behavior.md)
- [Frozen promotion protocol](docs/revenue-upgrade-protocol.md)

The nominal 80% revenue interval covered **70.724%** of fresh Canadian targets
and **87.037%** of NZ targets. Canadian undercoverage remains a limitation.
The financial backtest uses disclosed synthetic costs: expected seasonality
gave 0 overload months versus 7 for equal payments; an unexpected flat future
gave 4 versus 0. Neither is proof of actual borrower repayment performance.
Consumed holdouts cannot become fresh evidence for subsequent tuning.

## Validate

```bash
pnpm check
python3 -m unittest discover -s tests/operations -v
uv run --frozen --directory hybrid-runtime pytest
pnpm exec playwright install chromium
# Create isolated test databases once; never point tests at production.
docker compose exec -T db createdb -U wiut wiut_test
docker compose exec -T db createdb -U wiut wiut_no_ml
docker compose exec -T db createdb -U wiut wiut_final_ml
pnpm test:e2e
pnpm test:final-ml
git diff --check
```

The final integration suite exercises the actual assembled scorer through Nest
and the browser, including mobile layout, interest totals, isolation and durable
officer decisions. Borrower test inputs remain disclosed synthetic fixtures.
The standard suite also tests actual disconnected-ML failures. Database overrides
are `WIUT_TEST_DATABASE_URL`, `WIUT_NO_ML_DATABASE_URL`, and
`WIUT_FINAL_ML_DATABASE_URL`. Frozen historical suites and training recipes are
documented in [research reproduction](docs/research/README.md).

## Limits and attribution

Public data supplies aggregate revenue and card-spend proxies, with **no actual
borrower expense, repayment or default labels**. Costs are projected from observed
transactions without category/debt classification. Short-history forecasts are
weak. Confidence and interval coverage are not repayment probabilities. Native
publisher currencies and index units are never silently converted to borrower UZS.
Import provenance is declared by the importer; statements are not authenticated.

This MVP has no email verification, bank connector or credit origination system.
Run one API process and one ML worker. Its local rate limiter is not distributed.
Lists are bounded (200 businesses, 100 attempts, 500 audit events), and summary
counts describe returned records. Banking deployment requires a controlled pilot
and the bank's operational review. No validated bank savings or loan-loss impact
is claimed.

The React/Nest foundation comes from
[nest-react-boilerplate](https://github.com/nmime/nest-react-boilerplate) at
`2e10b3298956b887065e0b87cac23ab57335a397`; the upstream MIT
[licence](LICENSE) is preserved. [Upstream attribution](docs/upstream.md) identifies
the imported baseline. The teammate supplied the frozen financial module and
synthetic artifacts; its [source attribution and SHA manifest](teammate-ml-service/README.md)
are retained. Official shadcn/ui components and Tailwind form the UI.

```text
apps/frontend/app/                One React/Vite application
apps/backend/user/user-app-api/   One NestJS/Fastify API, PostgreSQL and audit
libs/common/api-contracts/        Shared validated transport schemas
ml-service/final_model/           Final scorer and verified accepted assets
hybrid-runtime/                  Pinned production inference environment
ml-service/capacity_ml/           Frozen original training and forecast source
teammate-ml-service/              Attributed frozen financial source and research
tests/                           Isolated unit, API and browser verification
docs/                            Deployment, sources, evidence and submission
```
