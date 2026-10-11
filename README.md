# FlowCredit · WIUT Hackathon

A bank/team workspace for importing business transactions and reviewing cash flow,
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
Tables are initialized automatically. New workspaces start empty; records and
review decisions survive restarts. Legacy demo businesses are archived once
without deleting their saved assessments or decisions.

Create an account with a bank/team workspace name at the sign-up screen, or use
an administrator's invitation link. Accounts use email and a password of at least
12 characters. Each workspace has an isolated portfolio. Import a business to
begin. An upgraded installation retains its existing workspace and saved history;
new registrations and additional workspaces receive no seeded businesses.
For demonstrations and tests, open **Showcase lab** and opt in to a separate
workspace with seeded, explicitly synthetic scenarios. Generated cases use the
normal scoring and human-review flow and include provenance in their exports.
They stay separate from bank portfolios. See [Showcase lab](docs/showcase.md).
For authenticator setup, generate a persistent local encryption key with
`openssl rand -hex 32` and put it in `AUTH_ENCRYPTION_KEY` in the ignored `.env`.
Preserve that key across restarts and backups; production setup generates it automatically.

The ML service is optional during frontend/backend development. With
`ML_SERVICE_URL` empty, business histories, imports, and audit views work;
analysis returns a clear unavailable error and records the failed attempt.
No fabricated score or recommendation is substituted.

## Run the included local ML service

The repository includes one final local FastAPI scorer. It combines a revenue
forecast trained on licensed public turnover observations, real-revenue interval
calibration, observed business costs, seasonal affordability, 24% annual interest,
and three advisory verdicts. To run the complete application locally:

```bash
docker compose -f docker-compose.yml -f docker-compose.ml.yml up --build -d
```

Open http://localhost:8080. The ML container loads the frozen final model and NestJS
connects to `http://ml:8000`. The ML API listens on localhost:8000 and retains
request hashes, responses, and model identifiers in the `ml-audit` volume.
Inference and explanations make no external API calls.

For Python development, install [uv](https://docs.astral.sh/uv/getting-started/installation/),
then run the final scorer:

```bash
uv sync --frozen --directory hybrid-runtime
./scripts/serve_final_model.sh
```

Set `ML_SERVICE_URL=http://127.0.0.1:8110` for the local NestJS process.
The [final model runtime](docs/final-model-runtime.md) documents the combined
forecast, real-calibrated uncertainty, 24% annual interest, seasonal capacity,
three advisory verdicts, component identities, and human review.

The original forecast training and historical evaluations remain reproducible
in their separate frozen environment:

```bash
cd ml-service
uv sync --frozen
uv run python -m capacity_ml.train
uv run python -m capacity_ml.evaluate
uv run python -m capacity_ml.evaluate_public
uv run python -m capacity_ml.evaluate_revenue
uv run python -m capacity_ml.evaluate_international
uv run python -m capacity_ml.evaluate_external
uv run python -m capacity_ml.evaluate_engineering
uv run pytest
uv run uvicorn capacity_ml.api:app --host 127.0.0.1 --port 8000
```

See [ML implementation and measured evaluation](ml-service/README.md) for the
generator, split, forecast selection, capacity factors, and limitations.
The [public dataset declaration](ml-service/data/README.md) documents official
sources, CC BY 4.0 attribution, quality exclusions, and calibration windows.
The corpus includes Uzbekistan revenue, Australian/Canadian retail sales and
30 European countries' nominal turnover indices. New European/UK snapshots add
72,141 published observations; 90,819 missing entries remain null. Training
rejects affected windows instead of inventing sales. Real training now uses
86,976 rolling target examples (43,705 unique target observations), with equal
provider loss weights. Overlapping windows are not independent businesses.
A richer seasonal/harmonic residual ensemble adapts using only already observed
borrower history. Joint validation selects its downstream blend and cost policy.
The [external audit](ml-service/reports/external-metrics.md) covers reserved
Eurostat countries plus the entire UK ONS provider; ONS is never fitted or used
for selection. It measured 19.3% lower normalized revenue error than seasonal
naive on 816 future observations in six usable country clusters. The real
revenue component stays frozen after this audit; subsequent runs reproduce its
measured result. A [synthetic engineering audit](ml-service/reports/engineering-metrics.md)
checks the scoring path on 900 separately reserved businesses. The first
180-business audit rejected a guarded blend because its average real contribution
was 49.7%, below the frozen 50% requirement; its failed report is retained.
A subsequent fixed 50/50 candidate improved overall error but worsened the
pattern-break cohort by 20.7%, beyond the unchanged 15% limit. The third audit
rejected a 75%/25% guarded candidate: overall error improved by 4.9%, but the
pattern-break cohort worsened by 15.7%. All three failures are retained. Cost and
blend revisions use the original development data,
with the real-revenue component fixed. The final 65%/25% policy passed all
unchanged guards on 900 newly reserved businesses: mean real contribution was
53.2%, and macro normalized net-flow error improved by 5.5% (descriptive 95%
interval 4.4–6.6%). Pattern-break error still worsened by 11.0%; the preset guard
allows at most 15%. Short or recently unstable histories receive 25% real
contribution; established histories receive 65%, reducing their synthetic share
from 90% to 35%. These components include statistical forecasts and observed-cost
assumptions, so their weights are not percentages of correct predictions.
Each first audit uses separately reserved seeds; this fourth sequential cycle
remains exploratory, and reruns reproduce consumed targets. Previously reported
Uzbekistan, ABS/Canada and synthetic periods are explicit legacy regressions.
Country clusters, short-history failures and uncertainty are reported honestly.
Native currencies and publisher index points are never pooled across sources.
Public revenues contain no borrower expense, repayment or default labels.
The scoring model includes real-trained revenue only when validation improves
the net forecast and passes normalized-error checks. Its actual blend and
expense policy are disclosed in structured forecast provenance, model flags,
rationale and `/health`, and visible in the review workspace.
Fully inactive histories return zero without estimator provenance; expense-only
histories disclose their zero-revenue guard instead of claiming learned revenue.
The included repayment model uses explicitly declared **0% interest**;
recommendations use the imported business's declared units and require human review.
Python and NestJS validate payment totals against the recommended principal;
contradictory schedules fail the assessment rather than being saved as results.
The ML health endpoint and durable audit identify the exact loaded artifact by
SHA-256. Builds on different platforms can fit slightly different predictors;
their consumed-cohort checks retain separate metrics and the same acceptance
limits, rather than claiming identical model bytes or additional fresh evidence.

## Connect the teammate's ML service

The supplied teammate service is integrated in `teammate-ml-service/` as a private,
optional candidate. Its LightGBM artifacts remain unchanged. It adds native
forecast intervals, requested-amount checks and interest-bearing schedules at
**24% annual interest**. It trained on synthetic businesses, so it does not
establish an accuracy improvement on real borrowers. The assembled final scorer
is the product default. See the [independent review](docs/teammate-ml-review.md) and
[candidate setup](teammate-ml-service/README.md).

Run the candidate on loopback port 8111 as documented there, set
`ML_SERVICE_URL=http://127.0.0.1:8111` in `.env`, then restart the API.
The adapter posts to `${ML_SERVICE_URL}/score`. The contract is documented in
[ML integration](docs/ml-integration.md) and enforced by the shared schemas in
`libs/common/api-contracts/src/index.ts`. The default timeout is 8 seconds.
The candidate requires a completed month-end and at least six complete history
months; refusals are saved as failed attempts with an actionable message. The
product never substitutes a fabricated score. Production selection and private
container startup are described in [deployment](docs/deployment.md).

The [model comparison](docs/model-comparison.md) explains their training data,
forecast targets, repayment policies and validation evidence. Their reported
errors use different datasets and targets and do not establish an accuracy winner.

Imports accept user-provided transactions in UZS. Core scoring runs in the local
Python service and does not require external AI calls. Public-data training and
synthetic model components remain explicitly disclosed; accepting actual inputs
does not establish real borrower accuracy.

## Main workflow

1. Sign in and select your bank/team workspace. Import business transactions
   from CSV or JSON, then select the business.
2. Review the historical cash-flow chart and transaction records.
3. Choose an assessment date and optionally enter the requested amount in UZS.
4. Analyze using the connected ML service.
5. Inspect capacity, confidence, warnings, explanations, forecast, and payments.
6. Record approval, decline, or a request for more information with reasoning.
   The API records the signed-in reviewer's identity. A recorded decision is
   immutable; reassess for a new review.
7. View assessment history and its audit trail, or download the result as JSON.

User-provided histories declare `amount_unit: "UZS"`; the API maps one UZS to
one internal `amount_index` unit. Cash flows and assessment amounts preserve
that unit snapshot. Legacy synthetic histories retain **index** units and are
never relabeled as currency. The default scorer does not receive this unit
declaration: an optional UZS `requested_amount` remains context only, is flagged,
and does not cap its recommendation. Officers must check the requested amount
when reviewing. See [transaction imports](docs/imports.md).
The optional teammate candidate explicitly treats one internal unit as one UZS
and checks requested amounts against its native capacity limits; its actual rate,
schedule type and total interest are shown in saved results and exports.

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

Open **Account security** to change your password, enable an authenticator,
and generate an offline account recovery key. Authenticator setup returns ten
single-use backup codes; these replace an authenticator code when signing in or
confirming security changes. The separate account recovery key resets a forgotten
password, disables MFA and revokes every session. Save both offline when displayed:
the application stores their hashes and cannot display them again. No email
delivery is required. See [account security](docs/account-security.md).
Scheduled backups and local health monitoring are documented in
[operations](docs/operations.md).

## Verify

```bash
pnpm check
python3 -m unittest discover -s tests/operations -v
# Create an isolated browser-test database once:
docker compose exec -T db createdb -U wiut wiut_test
docker compose exec -T db createdb -U wiut wiut_no_ml
pnpm exec playwright install chromium
pnpm test:e2e
git diff --check
```

Tests cover transport validation, test-fixture generation, empty workspaces,
UZS CSV/JSON imports and exports, legacy migration preservation, authentication, roles,
invitations, CSRF, tenant isolation, ML failures, durable human review, and the
browser workflow. The browser-test ML fixture is exclusively
test infrastructure and is never started by the product's dev or Docker commands.
`WIUT_TEST_DATABASE_URL` and `WIUT_NO_ML_DATABASE_URL` may override the browser-test
connections. The second database verifies the actual disconnected-ML behavior.

After preparing the final runtime, test the actual final scorer through NestJS
and the browser in a separate test database:

```bash
docker compose exec -T db createdb -U wiut wiut_final_ml
pnpm test:final-ml
```

This suite uses ports 8112/3012/5178. `WIUT_FINAL_ML_DATABASE_URL` may override
its connection. Borrower inputs are disclosed synthetic integration fixtures.

The original frozen scorer has a separate regression suite:

```bash
docker compose exec -T db createdb -U wiut wiut_real_ml
pnpm test:real-ml
```

This suite uses the `wiut_real_ml` database and separate service ports. Its
`WIUT_REAL_ML_DATABASE_URL` connection can be overridden.

Verify the optional candidate independently:

```bash
cd teammate-ml-service
uv sync --frozen
uv run pytest -q
cd ..
docker compose exec -T db createdb -U wiut wiut_teammate_ml
pnpm test:teammate-ml
```

Its browser suite uses a separate database and ports 8111/3011/5177. It never
changes the default model or supplies additional real-borrower accuracy evidence.

## Container stack

```bash
docker compose up --build -d
```

Open http://localhost:8080. Nginx serves the built frontend and proxies `/api` to
NestJS; PostgreSQL stores the audit and case records in a named volume. Local
ports bind to loopback. Set a strong `POSTGRES_PASSWORD` before hosting.
For an ML container, set `ML_SERVICE_URL` to an address reachable from the API
container (a Compose service name or `host.docker.internal`, not its localhost).
For HTTPS hosting with persistent storage and secure cookies, see
[production deployment](docs/deployment.md).

## Data declaration and limitations

New workspaces contain no demo businesses. Imports must contain the business's
actual UZS amounts and declare `data_source: "user_provided"`. This declaration
records provenance supplied by the importer; the application cannot verify that
a bank export is authentic. Historical synthetic cases remain directly accessible
to their tenant from saved links, with their original indexed results and audits.
They are excluded from active portfolio, review and audit lists. The deterministic
business generator remains test infrastructure; it never runs during registration,
workspace creation, development startup or production startup.

This MVP has authenticated tenant access, role administration, opt-in MFA,
offline account recovery and human review. It has no email verification, banking
connector, or credit origination integration. Public revenue data supplies neither borrower default
nor repayment ground truth. Real banking use requires additional account and
operational controls.
Run one API process per database; startup recovers interrupted pending assessments
as failed attempts. Use the separate `wiut_test` database for browser tests.
List views show the newest 200 businesses, 100 assessment attempts, and 500 audit
events. Overview counts describe the returned records, not unbounded portfolio totals.
The optional ML service has its own synthetic generator and measured held-out
evaluation. Its report describes performance on unseen synthetic businesses and
future months; it does not establish real borrower performance or default risk.
The historical teammate endpoint can be selected without changing the frontend.
The final assembly uses its verified financial primitives and real-revenue
forecasting; real borrower repayment accuracy remains unverified.

## Repository

```text
apps/frontend/app/                  React, Tailwind, official shadcn/ui
apps/backend/user/user-app-api/      NestJS, PostgreSQL, ML adapter, audit
libs/common/api-contracts/           Runtime schemas and shared TypeScript types
ml-service/                         Final scorer, frozen forecast recipe and evidence
hybrid-runtime/                     Pinned combined inference environment
teammate-ml-service/                Frozen teammate candidate and private adapter
tests/                              Isolated API and browser integration tests
docs/                               ML contract and fork provenance
```

The upstream MIT license is preserved in [LICENSE](LICENSE).
