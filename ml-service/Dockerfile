FROM ghcr.io/astral-sh/uv:0.11.28 AS uv
FROM python:3.12.13-slim

COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    ML_MODEL_PATH=/app/runtime/model.joblib \
    ML_AUDIT_PATH=/data/audit/requests.jsonl \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev
COPY capacity_ml ./capacity_ml
COPY data ./data
RUN uv run --frozen --no-dev python -m capacity_ml.train > /app/training-metadata.json
RUN groupadd --gid 10001 ml \
    && useradd --uid 10001 --gid ml --no-create-home ml \
    && mkdir -p /data/audit \
    && chown 10001:10001 /data/audit \
    && chmod 0444 /app/runtime/model.joblib

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "capacity_ml.api:app", "--host", "0.0.0.0", "--port", "8000"]
