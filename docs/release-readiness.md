# Final release readiness

The product serves one final scorer. Historical model environments and reports
remain solely for reproducible research. The React application has no model
selector. The production Compose stack contains `db`, `ml`, `api` and `web`;
the API connects to the final scorer at `http://ml:8000`.

## Checks on the exact release tree

Use Node 24, pnpm 12.8.1 and the committed Python lockfiles. Run:

```bash
pnpm check
python3 -m unittest discover -s tests/operations -v
uv run --frozen --directory hybrid-runtime pytest
uv run --frozen --directory teammate-ml-service pytest
pnpm test:e2e
pnpm test:final-ml
git diff --check
```

Browser suites use isolated test databases; their transactions are disclosed
synthetic fixtures. Never run them against production. The final suite covers
the actual assembled scorer, interest and total repayment, material offers,
tenant isolation, persisted human decisions and desktop/mobile presentation.

## Deploy and verify

Follow [deployment](deployment.md) and [operations](operations.md). Build from a
clean committed checkout, preserve existing database/authentication keys and
audit volumes, and use the deployment script's pre-migration backup and rollback
images. Retire the old scorer container only after the final stack is healthy.
Do not remove volumes or reseed bank workspaces.

Public `/release.json` identifies the source commit, bundle and verified model
hashes. Compare it with `main`; do not infer deployment from a Git push. Private
model health must report final mode, 24% nominal annual interest and required
human review. Explicitly accept the new verified assembly in monitoring only
after inspecting the release. Run a new backup and the private scoring probe,
which verifies actual responses and durable audit events.

The current financial assembly is `final-v1-9391d577e3c718a2`. The reproducible
[local timing report](runtime-latency.json) measures that assembly and explicitly
excludes Nest, network, browser and cloud load. It is not a production SLA.

## Source and evidence

[Data sources](data-sources.md), [upstream attribution](upstream.md),
[final runtime](final-model-runtime.md) and [history reorganization](git-history.md)
identify reused components, licensed observations, frozen evidence and preserved
original history. Public revenue data supplies no actual borrower expense,
repayment or default labels. Synthetic accounting checks do not establish real
borrower accuracy.

The team prepares its own presentation and handles portal submission manually.
No generated presentation or rehearsed business proposal is included in this
repository. After the 11 October 2026, 13:00 Tashkent code freeze, redeploy only
the identical submitted commit if the organiser permits it.
