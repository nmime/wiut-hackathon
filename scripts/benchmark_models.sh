#!/usr/bin/env bash
# Reproduce the paired revenue experiment without changing either serving model.
set -euo pipefail

benchmark_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
benchmark_source_model=${1:-"$benchmark_root/ml-service/runtime/model.joblib"}
benchmark_output="$benchmark_root/artifacts/model-benchmark"
benchmark_frozen="$benchmark_output/frozen/default.joblib"

if [[ ! -f "$benchmark_source_model" ]]; then
  echo "Supply a trusted frozen default model: bash scripts/benchmark_models.sh /absolute/path/model.joblib" >&2
  exit 1
fi
mkdir -p "$benchmark_output/frozen"
if [[ -f "$benchmark_frozen" ]]; then
  if ! cmp -s "$benchmark_source_model" "$benchmark_frozen"; then
    echo "The existing frozen artifact differs. Preserve this experiment and use a separate checkout for another artifact." >&2
    exit 1
  fi
else
  install -m 444 "$benchmark_source_model" "$benchmark_frozen"
fi

export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
cd "$benchmark_root"
uv run --frozen --directory ml-service python -m benchmarks.compare_real_revenue prepare-development
uv run --frozen --directory teammate-ml-service python benchmark/revenue_runner.py \
  --input "$benchmark_output/development-input.json" \
  --output "$benchmark_output/development-vendor.json" --native-unit-diagnostic
if [[ -f "$benchmark_output/real-lgb/real_lgb_manifest.json" ]]; then
  uv run --frozen --directory teammate-ml-service python - \
    "$benchmark_output/training.npz" "$benchmark_output/real-lgb/real_lgb_manifest.json" <<'PY'
import hashlib
import json
import pathlib
import sys

actual = hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()
expected = json.loads(pathlib.Path(sys.argv[2]).read_text())["training_npz_sha256"]
if actual != expected:
    raise SystemExit("Frozen experimental training data changed; preserve the original experiment.")
PY
  uv run --frozen --directory teammate-ml-service python benchmark/real_lgb_runner.py \
    --input "$benchmark_output/development-features.json" \
    --output "$benchmark_output/development-real-lgb.json" \
    --artifact-dir "$benchmark_output/real-lgb"
else
  uv run --frozen --directory teammate-ml-service python benchmark/real_lgb_runner.py \
    --train "$benchmark_output/training.npz" \
    --input "$benchmark_output/development-features.json" \
    --output "$benchmark_output/development-real-lgb.json" \
    --artifact-dir "$benchmark_output/real-lgb"
fi
uv run --frozen --directory ml-service python -m benchmarks.compare_real_revenue select
uv run --frozen --directory ml-service python -m benchmarks.compare_real_revenue prepare-terminal
uv run --frozen --directory teammate-ml-service python benchmark/revenue_runner.py \
  --input "$benchmark_output/terminal-input.json" \
  --output "$benchmark_output/terminal-vendor.json" --native-unit-diagnostic
uv run --frozen --directory teammate-ml-service python benchmark/real_lgb_runner.py \
  --input "$benchmark_output/terminal-features.json" \
  --output "$benchmark_output/terminal-real-lgb.json" \
  --artifact-dir "$benchmark_output/real-lgb"
uv run --frozen --directory ml-service python -m benchmarks.compare_real_revenue report \
  > "$benchmark_output/report-summary.json"
echo "Measured evidence: ml-service/reports/real-model-benchmark.json and real-model-benchmark-predictions.json"
