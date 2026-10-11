# Frozen research and regression

Production serves one [final scorer](../final-model-runtime.md). The original
forecast environment, teammate bridge, source, artifacts and reports remain
because deleting them would prevent reproduction and erase failed experiments.
Do not configure production to select these historical endpoints.

- [Original training and evaluation](../../ml-service/README.md)
- [Teammate source, archive attribution and SHA manifest](../../teammate-ml-service/README.md)
- [Historical contract and policy notes](historical-ml-contract.md)
- [Common real-revenue comparison](../../ml-service/reports/real-model-benchmark.md)
- [Fresh holdout experiment and frozen gate decision](../../ml-service/reports/revenue-upgrade-fresh.md)
- [Model comparison and component rationale](../model-comparison.md)

The original `ml-service/uv.lock` and `teammate-ml-service/uv.lock` are frozen
research environments. `hybrid-runtime/uv.lock` is the separate production
inference environment. Builds of the final service load accepted committed
assets without fitting. Vendor code remains byte-for-byte verified.

From the root, the historical regression suites are:

```bash
docker compose exec -T db createdb -U wiut wiut_real_ml
docker compose exec -T db createdb -U wiut wiut_teammate_ml
pnpm test:real-ml
pnpm test:teammate-ml
uv run --frozen --directory ml-service pytest
uv run --frozen --directory teammate-ml-service pytest
```

These suites start isolated loopback services and dedicated test databases.
They use disclosed synthetic borrower fixtures to check transport and behavior,
not real borrower accuracy. Never point a test database URL at production.

Snapshot licences, native units, reservations, model versions and source hashes
are retained. A rerun of a consumed holdout is a regression, not new evidence.
Reserve a different holdout before tuning or making another replacement claim.
Historical Dockerfiles and vendor README instructions are source material;
the product's only production image is `hybrid-runtime/Dockerfile`.
