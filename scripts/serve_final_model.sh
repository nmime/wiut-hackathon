#!/usr/bin/env bash
set -euo pipefail

final_runtime_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONPATH="$final_runtime_root/ml-service:$final_runtime_root/teammate-ml-service${PYTHONPATH:+:$PYTHONPATH}"
export FINAL_MODEL_BUNDLE="${FINAL_MODEL_BUNDLE:-$final_runtime_root/ml-service/final_model/artifacts}"
export ML_AUDIT_PATH="${ML_AUDIT_PATH:-$final_runtime_root/hybrid-runtime/runtime/final-audit.jsonl}"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

exec uv run --frozen --directory "$final_runtime_root/hybrid-runtime" \
  uvicorn final_model.api:app --host "${FINAL_MODEL_HOST:-127.0.0.1}" \
  --port "${FINAL_MODEL_PORT:-8110}" --workers 1
