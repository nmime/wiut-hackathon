# Teammate ML candidate review

Reviewed on 2026-10-11. Keep the existing frozen real-revenue blend as the default
and connect the teammate scorer as an explicitly selected private candidate. The
teammate implementation adds useful forecast intervals and genuine interest-bearing
repayment planning. The supplied evidence does **not** establish that it predicts
actual borrower cash flow more accurately than the current model.

The maintainer authorized integration. An adapter can address the transport and
operational problems below while preserving the teammate's trained artifacts and
mathematics. Changing its calibration or training would create a new candidate,
requiring its own version and evaluation.

## Reviewed material and independent checks

- Original archive: `ml-service.zip`, supplied by the maintainer. SHA-256:
  `c0a062c8b700fe0824fbcb746db4615d1fab3ad8c7360adf7133e706ea2039db`.
- Original explanatory document: `Untitled.docx`. Its 501 paragraphs were read as
  source material; the document rendered successfully to 21 pages. The forecast
  metric table and architecture diagram were visually checked.
- All 93 ZIP entries were validated **before extraction**: no absolute/traversal
  paths, symlinks, other special files, encrypted entries, duplicate paths or
  suspicious expansion. The archive contains 5,780,471 uncompressed bytes.
- Extracted source was inspected before execution. Dependencies and tests ran in
  a separate Python 3.12.13 environment, with the optional external LLM disabled.
  Existing model environments and artifacts were unchanged.
- **49 teammate tests passed in 29.09 seconds.** One FastAPI/Starlette test-client
  deprecation warning was emitted. Network-disabled inference is covered by the
  supplied tests.
- Independent probes confirmed a valid fixture assessment, failure/audit behavior,
  unauthenticated record/decision routes and artifact identity limitations.

Ignored local evidence lives under `artifacts/teammate-ml-review/`: extraction and
archive manifests, `teammate-document.txt`, rendered pages, `review_probes.py`,
`probe-results.json` and isolated audit files. This directory is review evidence,
not product data or model training input. Every transaction used in these probes
is an explicitly synthetic test fixture.

The original full six-seed training/evaluation and 100,000-row latency benchmark
were **not independently rerun** in this review. Their figures below are clearly
identified as author-supplied reports, rather than newly measured results.

## What the candidate implements

The shipped model is `m-f7d2fc389743`, generator `gen-1.0.0`, service `0.1.0`.
Its metadata reports training on 420 synthetic businesses, 91 validation businesses
and 65,709 supervised rows from seed 42. Two native LightGBM text artifacts predict
inflow and operating outflow separately. Seasonal history, trend, channel mix,
calendar/Ramadan features and industry priors contribute to the forecast.

The service computes P10/P50/P90 forecasts, a conservative P10 payment tier and
an optional P20 tier. Its score describes the modeled chance that monthly free
cash flow exceeds a learned reference load, about 29.5% of mean inflow. This is
neither default probability nor a calibrated probability for real borrowers.
Confidence combines history and interval-width factors; it is an evidence
indicator, not a separate accuracy guarantee.

Loan planning supports annuity and adaptive principal amortization, explicit
interest and balance rows, terms from 3 to 36 months, and requested-amount
constraints. The default is **24% annual interest**, with 12 months by default.
The 12-month forecast is repeated for longer terms, which needs clear disclosure.
All final product decisions must continue to be recorded by authenticated humans
through NestJS.

## Contract and product integration

| Area         | Current product contract                                                                 | Original teammate contract                                                                                                                     | Required bridge behavior                                                                                                               |
| ------------ | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Transport    | JSON `POST /score`, shared validated request/response                                    | Multipart `POST /v1/assess`; `/score` returns 404                                                                                              | Implement private JSON adapter and validate both sides                                                                                 |
| Transactions | `ts`, direction, channel, internal `amount_index`; declared UZS import conversion is 1:1 | CSV requires business ID, transaction ID, timestamp, amount, direction, channel                                                                | Generate deterministic transport IDs; map field/channel names; preserve declared units                                                 |
| Metadata     | Minimal user-provided imports do not contain categories, counterparties or debt labels   | Optional category, counterparty ID, OKED, external debt                                                                                        | Omit unavailable columns and disclose missing information; never infer labels as fact                                                  |
| History      | Illustrative short-history result, with loan suppressed when evidence is inadequate      | Under 6 full months refused; 6–11 without adaptive seasonality; 12–23 reduced; 24+ full                                                        | Preserve explicit refusal; never invent forecast arrays to satisfy the shared schema                                                   |
| Calendar     | Supplied calendar date/month retained; forecast starts after assessment month            | Offsets normalized to Tashkent; first month can be dropped if first transaction day is at least 10; month-end assessment month may be retained | Preserve existing date grouping in the adapter and disclose intentional history-window differences                                     |
| Repayment    | Existing frozen model uses a declared 0% MVP policy                                      | Genuine annuity/adaptive interest, 24% default                                                                                                 | Preserve actual rate, term, payment, principal and interest; expose them in UI/export; never attach `zero_interest_mvp` to this result |
| Identity     | Nest validates business/date, stores full response and immutable first human decision    | Independent UUID and vendor audit/decision routes                                                                                              | Preserve product request identity; keep Nest as tenancy and decision authority                                                         |

The original service's static demo and synthetic-generation endpoint should not be
mounted in the empty real-data MVP. Only private health/scoring routes should be
available to the Nest service. Missing-category imports cannot reproduce the
candidate's own-transfer exclusion or separated debt treatment; these benefits
are conditional on actually providing that metadata.

Payment totals may exceed principal when genuine interest is present. An equal
payment comparison based only on total repayment is not automatically the
candidate's annuity amortization. The product must label this comparison accurately
or consume its actual annuity schedule.

## Confirmed problems in the original service

Source references below are relative to the extracted archive's `ml-service/`.
These findings concern the original vendor service; an isolated wrapper can
guard them without changing its forecast equations.

1. **Unaudited runtime failures.** `as_of_date="2025-99-99"` passes the string
   pattern in `api/schemas.py:34`, then fails date construction in
   `api/service.py:91`. A valid file containing only `category=transfer_own`
   reaches an empty profile and fails during `features/profile.py:119`–121. Both
   independently returned HTTP 500 and left audit counts unchanged. The endpoint
   at `api/main.py:92` catches only `InputError`. Validate actual calendar dates,
   explicitly refuse an empty usable profile and durably audit all failed attempts.
   In contrast, malformed CSV and invalid `issue_month="2025-99"` returned 422
   and added rejection audit entries in the probes.
2. **Unscoped record access and arbitrary officer identity.** An anonymous client
   read the full assessment, then recorded both approval and rejection for the
   same request; all three operations returned 200. See `api/main.py:107` and
   `api/main.py:118`. Do not expose these routes through the product. Use the
   existing Nest session, tenant scope and immutable decision transaction.
3. **Limits are checked after reading the upload.** `api/main.py:83` reads both
   uploaded files completely; `api/service.py:56` subsequently checks the
   transaction file's 50 MiB size. The optional business CSV has no equivalent
   explicit byte check there. Bound the incoming JSON stream before buffering,
   retain the product's event/calendar/amount caps, and avoid the vendor multipart
   endpoint in the public request path.
4. **Audit durability and integrity claims are too strong.** `api/audit.py:58`
   appends and flushes without `fsync`; its lock is process-local. Startup
   reindexes without verifying the chain. Independently removing the final line
   changed `verify()` from `{ok:true, records:2}` to `{ok:true, records:1}`.
   A hash chain cannot detect tail truncation without an independent anchor.
   Use one scoring process, wrapper audit fsync before releasing responses, and
   Nest persistence. Do not describe the original log as deletion-proof.
5. **Artifact version is not verified on loading.** The version computed in
   `models/train.py:188` hashes four files but excludes industry priors,
   population data, source and training-data identity. `models/registry.py:35`
   accepts the metadata version without recomputing it. On a copied artifact
   directory, changing metadata to `review-only-forged-version` still loaded.
   Verify a complete source/artifact manifest at startup and record its actual
   digest in every wrapper audit event.

The valid stable synthetic fixture independently produced HTTP 200, score 96.7
and annual rate 0.24. This confirms working inference and actual interest-bearing
output, not forecast accuracy on unseen business outcomes.

## Accuracy evidence and temporal limitations

The supplied reports compare synthetic test businesses and 12 generated future
months against seasonal naive and ETS. They include structural shocks, short
histories, and cases where adaptive repayment loses. These are useful engineering
checks, and they openly distinguish capacity from default classification.

| Author-supplied metric                             | Seeds 42–44           | Seeds 45–47           |
| -------------------------------------------------- | --------------------- | --------------------- |
| Inflow WAPE, candidate / ETS / seasonal naive      | 0.218 / 0.236 / 0.257 | 0.186 / 0.207 / 0.236 |
| Free-flow WAPE, candidate / ETS / seasonal naive   | 0.441 / 0.568 / 0.525 | 0.398 / 0.510 / 0.482 |
| P10–P90 free-flow interval coverage; nominal 80%   | 75.2%                 | 76.6%                 |
| Conservative payment coverage among nonzero offers | 92.3%                 | 90.7%                 |
| Businesses receiving a nonzero conservative offer  | 66.2%                 | 71.2%                 |

These are supplied values from `eval/reports/report.md` and
`eval/reports/fresh_seeds_45_47/report.md`, not independently reproduced here.
Coverage among nonzero offers must be read with utilization and refusal/offer
rates. The reported intervals under-cover their nominal level. Declining
businesses perform worse than ETS in both sets; there is no uniform win.

Two material qualifications apply:

- **OOF calibration is not completely isolated by business.**
  `models/train.py:128` computes industry priors from all training businesses and
  builds rows before constructing the grouped folds at line 134. Those priors
  include the later held-out fold's full histories. Fold boosters exclude those
  rows, but their feature priors and capacity backtests reuse the full-population
  priors at line 167. `models/forecast.py:192` confirms priors use the full profile
  rather than an origin-limited profile. Refit priors inside each calibration fold
  for a new candidate and remeasure coverage before asserting wholly unseen
  calibration. This finding does not show that final test-business labels were
  used to fit the shipped model.
- **The claimed control seeds were consumed before the final formula.** The DOCX
  explicitly states that seeds 45–47 were evaluated, then a payment formula was
  changed following a seed-42 demo, and both sets rerun. That is disclosed
  development history, not a fresh final confirmation. Each seed's evaluation also
  trains its own model; it does not demonstrate that the single shipped seed-42
  artifact transfers to all other cohorts unchanged.

The current frozen model `local-v4-bf33fb45ddc3-gradient_boosting-public65`
has licensed public-revenue training and preserved external/engineering audit
lineage in `ml-service/reports/`. Its expense/net-flow qualification remains
synthetic. Its score and confidence are declared heuristics; its baseline loan
policy is 0%. The candidate's WAPE, probabilistic score and interest-bearing loan
metrics cannot be compared numerically with these different targets, cohorts and
policies to declare a winner.

Before replacing the default, freeze both artifacts and run them on exactly the
same unseen histories and future cash-flow targets. Predeclare forecast error,
interval coverage, refusal/offer rate, capacity coverage, unit scaling and
same-principal/same-term/same-interest repayment comparisons. Retain cohort
failures and distinguish a common synthetic engineering test from evidence on
licensed actual revenue. Real revenue observations alone do not establish
expense, repayment or default performance.

## Provenance and release recommendation

The archive contains synthetic generator data and examples, not actual bank
observations. It has no code/model LICENSE file or supplied permission record;
retain teammate authorship and the supplied archive identity. The maintainer
authorized this project integration; do not invent an upstream license grant. The hardcoded public Ramadan calendar has no source
URL and only covers 2018–2029; add attribution and disclose out-of-range behavior.
Do not portray calendar features as licensed real revenue training.

Proceed with a private optional adapter that keeps vendor artifacts/source frozen,
uses full startup identity checks, bounds and validates input, validates the
converted shared response, records the original response and actual interest
rows durably, and preserves Nest's human decisions. Run candidate-specific API
and UI tests for successful UZS scoring, requested-amount limits, distinct business
outputs, insufficient history, persisted review/audit and interest disclosures.
Keep the real-revenue blend default until a common, honestly reported comparison
supports changing that choice.
