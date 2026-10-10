# WIUT Hackathon

This repository is a deliberately simplified product fork. The maintainer has
authorized removal of the upstream Nx/NRB platform, reference apps, aliases,
capability machinery, and tooling.

- Keep one React/Vite app at `apps/frontend/app` and one NestJS/Fastify API at
  `apps/backend/user/user-app-api`.
- Shared transport schemas live in `libs/common/api-contracts`.
- The optional local Python scoring service lives in `ml-service`. Keep it
  compatible with the same transport contract; the teammate may replace it.
- Use Node 24 and pnpm 12.8.1. Commit as
  `nmime <66474195+nmime@users.noreply.github.com>` without assistant trailers.
- Keep product work on a topic branch. Do not merge or deploy without a user request.
- Use official shadcn/ui components and Tailwind. Do not create custom reusable
  UI primitives or a second design system. Compose product pages from shadcn.
- Borrower profiles and demo transactions must be synthetic. Licensed public
  aggregates may calibrate the generator and support a separate revenue forecast
  benchmark, with attribution and honest evaluation. Never invent model outputs
  or metrics.
- The capacity score measures payment capacity, not default probability. A human
  records every final review decision.
- Amount indices must not be presented as currency without a declared conversion.
- Validate both incoming API data and responses from the ML service.
- Every assessment attempt and officer decision must be audited and persisted.
- Keep secrets and runtime data ignored. Document operational limitations honestly.
- Before finishing, run the type checks, builds, focused API/integration and browser
  tests, formatting check, and `git diff --check`.
