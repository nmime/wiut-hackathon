# FlowCredit · WIUT Hackathon

A bank/team workspace for reviewing synthetic business cash flow,
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

Create an account with a bank/team workspace name at the sign-up screen, or use
an administrator's invitation link. Accounts use email and a password of at least
12 characters. Each workspace has its own synthetic portfolio. The first account
on an upgraded installation adopts the existing demo workspace and its saved
assessments; later workspaces receive separate synthetic seeds.

The ML service is optional during frontend/backend development. With
`ML_SERVICE_URL` empty, business histories, imports, and audit views work;
analysis returns a clear unavailable error and records the failed attempt.
No fabricated score or recommendation is substituted.

## Run the included local ML service

The repository includes a local FastAPI service that trains its revenue forecast
on licensed Uzbekistan, Australian and Canadian sales data. Borrower expense
projections and synthetic net-flow forecasts are validated separately. To run
the complete demo:

```bash
docker compose -f docker-compose.yml -f docker-compose.ml.yml up --build -d
```

Open http://localhost:8080. The ML container builds its model locally and NestJS
connects to `http://ml:8000`. The ML API listens on localhost:8000 and retains
request hashes, responses, and model identifiers in the `ml-audit` volume.
Inference and explanations make no external API calls.

For Python development, install [uv](https://docs.astral.sh/uv/getting-started/installation/),
then run:

```bash
cd ml-service
uv sync --frozen
uv run python -m capacity_ml.train
uv run python -m capacity_ml.evaluate
uv run python -m capacity_ml.evaluate_public
uv run python -m capacity_ml.evaluate_revenue
uv run python -m capacity_ml.evaluate_international
uv run pytest
uv run uvicorn capacity_ml.api:app --host 127.0.0.1 --port 8000
```

Set `ML_SERVICE_URL=http://127.0.0.1:8000` for the local NestJS process.
See [ML implementation and measured evaluation](ml-service/README.md) for the
generator, split, forecast selection, capacity factors, and limitations.
The [public dataset declaration](ml-service/data/README.md) documents official
sources, CC BY 4.0 attribution, quality exclusions, and calibration windows.
The corpus includes 16,544 published Uzbekistan monthly points and 380 additional
Australian/Canadian retail series with 49,213 published numeric sales values and
9,487 missing/suppressed entries. Missing sales remain null;
training rejects affected windows instead of inventing values. The revenue
model uses 41,364 actual rolling target examples, with provider-balanced training
and validation. Overlapping windows are not independent observations.
The [international accuracy audit](ml-service/reports/international-metrics.md)
evaluates reserved terminal periods in unseen states/provinces, after selection
is frozen. Previously reported Uzbekistan and synthetic tests are explicitly
legacy regression benchmarks. Time boundaries are provider-specific, and native
currency errors are never pooled across countries.
Public revenues contain no borrower expense, repayment or default labels.
The scoring model includes real-trained revenue only when validation improves
the net forecast and passes normalized-error checks. Its actual blend and
expense policy are disclosed in model flags, rationale and `/health`.
The included repayment model uses explicitly declared **0% interest**;
recommendations remain indices and require human review.

## Connect the teammate's ML service

Set `ML_SERVICE_URL=http://127.0.0.1:8000` in `.env`, then restart the API.
The adapter posts to `${ML_SERVICE_URL}/score`. The contract is documented in
[ML integration](docs/ml-integration.md) and enforced by the shared schemas in
`libs/common/api-contracts/src/index.ts`. The default timeout is 8 seconds.

Only synthetic input is accepted by the import flow. Real bank data is outside
the scope of this prototype. Core scoring belongs to the bank-local Python
service and does not require external AI calls.

## Main workflow

1. Sign in and select your bank/team workspace. Select a synthetic business or
   import a synthetic transaction JSON file.
2. Review the historical cash-flow chart and transaction records.
3. Choose an assessment date and optionally enter the requested amount in UZS.
4. Analyze using the connected ML service.
5. Inspect capacity, confidence, warnings, explanations, forecast, and payments.
6. Record approval, decline, or a request for more information with reasoning.
   The API records the signed-in reviewer's identity. A recorded decision is
   immutable; reassess for a new review.
7. View assessment history and its audit trail, or download the result as JSON.

Transaction sizes, historical flows, and recommendation amounts are **indices**.
They are never relabeled as UZS. `requested_amount` is forwarded in UZS according
to the teammate's contract; the API does not invent an index conversion.

## Accounts and workspaces

Administrators open **Team & access** to invite an officer or another
administrator. Copy and share the returned invitation link; the application does
not send emails. Invitations expire after seven days, are bound to the invited
email, and can be revoked. A recipient can register with the link or sign in to
an existing account and accept it. Officers can assess and review their
workspace's businesses; team administration is restricted to administrators.

The workspace selector switches between memberships. Creating a workspace adds
an administrator membership there. Switching clears the browser query cache and
rotates the session's CSRF token. Signing out revokes the session. Business,
assessment, review, and audit queries are scoped to the active tenant. Foreign
resource IDs return a not-found response.

The API uses PostgreSQL sessions and HttpOnly, SameSite cookies. Authenticated
mutations require `X-CSRF-Token` from `/api/auth/session`; account registration,
login, and mutations also require a configured `Origin` header. Passwords are
hashed with scrypt. Login and registration are rate-limited by IP and email.
`SESSION_TTL_HOURS` defaults to 168 and `AUTH_RATE_LIMIT_MAX` to 20 attempts per
15 minutes. For HTTPS hosting, set `SESSION_COOKIE_SECURE=true`, use a strong
database password, and set `CORS_ORIGINS` to your exact application origin.
The loopback Docker preview explicitly uses HTTP cookies.
The API ignores forwarded client addresses by default. Compose enables exactly
one trusted proxy hop and Nginx overwrites the forwarded address with its actual
client address. Enable `TRUST_PROXY_HOPS=1` only when the API is reachable solely
through a trusted proxy that replaces client-supplied forwarding headers.
The limiter is process-local; run one API process per database for this MVP.

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

Tests cover transport validation, synthetic generation, authentication, roles,
invitations, CSRF, tenant isolation, ML failures, durable human review, and the
browser workflow. The browser-test ML fixture is exclusively
test infrastructure and is never started by the product's dev or Docker commands.
`WIUT_TEST_DATABASE_URL` and `WIUT_NO_ML_DATABASE_URL` may override the browser-test
connections. The second database verifies the actual disconnected-ML behavior.

After preparing the Python environment and training the local model, test its
real integration through NestJS and the browser:

```bash
docker compose exec -T db createdb -U wiut wiut_real_ml
pnpm test:real-ml
```

This suite uses the `wiut_real_ml` database and separate service ports. Its
`WIUT_REAL_ML_DATABASE_URL` connection can be overridden.

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

This is a synthetic-data hackathon MVP with authenticated tenant access. It has
no email verification, password recovery, MFA, banking connector, or credit
origination integration. Public revenues do not supply borrower default or
repayment ground truth. Real banking deployment requires additional account
and operational controls.
Run one API process per database; startup recovers interrupted pending assessments
as failed attempts. Use the separate `wiut_test` database for browser tests.
List views show the newest 200 businesses, 100 assessment attempts, and 500 audit
events. Overview counts describe the returned records, not unbounded portfolio totals.
The optional ML service has its own synthetic generator and measured held-out
evaluation. Its report describes performance on unseen synthetic businesses and
future months; it does not establish real borrower performance or default risk.
The teammate's service can replace it without changing the frontend.

## Repository

```text
apps/frontend/app/                  React, Tailwind, official shadcn/ui
apps/backend/user/user-app-api/      NestJS, PostgreSQL, ML adapter, audit
libs/common/api-contracts/           Runtime schemas and shared TypeScript types
ml-service/                         Optional local FastAPI model and evaluation
tests/                              Isolated API and browser integration tests
docs/                               ML contract and fork provenance
```

The upstream MIT license is preserved in [LICENSE](LICENSE).
