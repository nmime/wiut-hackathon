# FlowCredit · WIUT Hackathon

A credit-officer workspace for reviewing synthetic business cash flow,
explainable payment-capacity recommendations, and seasonal repayment schedules.
An officer records the final decision. The capacity score is not a default
probability.

The application is a simplified fork of the Nest React Boilerplate: one
React/Vite frontend, one NestJS/Fastify API, and shared Zod contracts.
See [source and cleanup](docs/upstream.md). The frontend uses Tailwind CSS and
official shadcn/ui registry components; product pages compose those primitives.

## Run locally

Requires Node 24, Corepack, and Docker for PostgreSQL.

```bash
corepack enable
pnpm install --frozen-lockfile
cp .env.example .env
pnpm db:up
pnpm dev
```

Open http://localhost:5173. The API listens on http://127.0.0.1:3000/api,
with Swagger documentation at `/api/docs`. PostgreSQL uses localhost:55432.
Tables and synthetic businesses are initialized automatically. Existing records
and review decisions survive restarts.

The ML service is optional during frontend/backend development. With
`ML_SERVICE_URL` empty, business histories, imports, and audit views work;
analysis returns a clear unavailable error and records the failed attempt.
No fabricated score or recommendation is substituted.

## Connect the teammate's ML service

Set `ML_SERVICE_URL=http://127.0.0.1:8000` in `.env`, then restart the API.
The adapter posts to `${ML_SERVICE_URL}/score`. The contract is documented in
[ML integration](docs/ml-integration.md) and enforced by the shared schemas in
`libs/common/api-contracts/src/index.ts`. The default timeout is 8 seconds.

Only synthetic input is accepted by the import flow. Real bank data is outside
the scope of this prototype. Core scoring belongs to the bank-local Python
service and does not require external AI calls.

## Main workflow

1. Select a synthetic business or import a synthetic transaction JSON file.
2. Review the historical cash-flow chart and transaction records.
3. Choose an assessment date and optionally enter the requested amount in UZS.
4. Analyze using the connected ML service.
5. Inspect capacity, confidence, warnings, explanations, forecast, and payments.
6. Record approval, decline, or a request for more information with reviewer name
   and reasoning. A recorded decision is immutable; reassess for a new review.
7. View assessment history and its audit trail, or download the result as JSON.

Transaction sizes, historical flows, and recommendation amounts are **indices**.
They are never relabeled as UZS. `requested_amount` is forwarded in UZS according
to the teammate's contract; the API does not invent an index conversion.

## Verify

```bash
pnpm check
# Create an isolated browser-test database once:
docker compose exec -T db createdb -U wiut wiut_test
docker compose exec -T db createdb -U wiut wiut_no_ml
pnpm exec playwright install chromium
pnpm test:e2e
git diff --check
```

Tests cover transport validation, synthetic generation, ML failures, durable
human review, and the browser workflow. The browser-test ML fixture is exclusively
test infrastructure and is never started by the product's dev or Docker commands.
`WIUT_TEST_DATABASE_URL` and `WIUT_NO_ML_DATABASE_URL` may override the browser-test
connections. The second database verifies the actual disconnected-ML behavior.

## Container stack

```bash
docker compose up --build -d
```

Open http://localhost:8080. Nginx serves the built frontend and proxies `/api` to
NestJS; PostgreSQL stores the audit and case records in a named volume. Local
ports bind to loopback. Set a strong `POSTGRES_PASSWORD` before hosting.
For an ML container, set `ML_SERVICE_URL` to an address reachable from the API
container (a Compose service name or `host.docker.internal`, not its localhost).
Public hosting is not provisioned by this repository.

## Data declaration and limitations

All seed businesses, names, locations, and transactions are synthetic. The
deterministic generator models monthly inflows with archetype-specific seasonality,
trend, volatility, and channel mixes, then samples transactions within each month.
It uses no customer records or external datasets. Imported data must explicitly
declare `data_source: "synthetic"`.

The seed generator is `apps/backend/user/user-app-api/src/synthetic.ts`. It uses
seeds `7261 + business_index × 919` and a fixed October 2025–September 2026
history window; the cold-start florist has only June–September 2026. Seeding is
idempotent. Generator and transport tests verify reproducibility.

This is a synthetic-data hackathon prototype with self-declared reviewer names.
It has no production authentication, authorization, banking connector, or credit
origination integration. Do not expose the prototype to real banking data.
Run one API process per database; startup recovers interrupted pending assessments
as failed attempts. Use the separate `wiut_test` database for browser tests.
List views show the newest 200 businesses, 100 assessment attempts, and 500 audit
events. Overview counts describe the returned records, not unbounded portfolio totals.
Measured model quality and failure-case evaluation belong to the teammate's ML
report; the interface does not invent metrics or claim trained-model accuracy.

## Repository

```text
apps/frontend/app/                  React, Tailwind, official shadcn/ui
apps/backend/user/user-app-api/      NestJS, PostgreSQL, ML adapter, audit
libs/common/api-contracts/           Runtime schemas and shared TypeScript types
tests/                              Isolated API and browser integration tests
docs/                               ML contract and fork provenance
```

The upstream MIT license is preserved in [LICENSE](LICENSE).
