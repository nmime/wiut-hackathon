FROM ghcr.io/astral-sh/uv:0.11.28 AS uv
FROM python:3.12.13-slim

COPY --from=uv /uv /uvx /usr/local/bin/
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/hybrid-runtime
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/hybrid-runtime/.venv/bin:$PATH" \
    PYTHONPATH="/app/ml-service:/app/teammate-ml-service" \
    FINAL_MODEL_BUNDLE=/app/ml-service/final_model/artifacts \
    ML_AUDIT_PATH=/data/audit/requests.jsonl \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

COPY hybrid-runtime/pyproject.toml hybrid-runtime/uv.lock hybrid-runtime/.python-version ./
RUN uv sync --frozen --no-dev
COPY ml-service/capacity_ml /app/ml-service/capacity_ml
COPY ml-service/data /app/ml-service/data
COPY ml-service/uv.lock /app/ml-service/uv.lock
COPY ml-service/final_model /app/ml-service/final_model
COPY teammate-ml-service/teammate_bridge /app/teammate-ml-service/teammate_bridge
COPY teammate-ml-service/hybrid /app/teammate-ml-service/hybrid
COPY teammate-ml-service/benchmark/improved_revenue.py /app/teammate-ml-service/benchmark/improved_revenue.py
COPY teammate-ml-service/vendor /app/teammate-ml-service/vendor
COPY teammate-ml-service/vendor-manifest.json /app/teammate-ml-service/vendor-manifest.json
# Startup verifies the committed measured artifacts. Image builds never retrain
# the revenue model or silently replace its accepted weights.
RUN groupadd --gid 10001 ml \
    && useradd --uid 10001 --gid ml --no-create-home ml \
    && mkdir -p /data/audit \
    && chown 10001:10001 /data/audit \
    && find /app/ml-service/final_model/artifacts -type f -exec chmod 0444 {} +

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "final_model.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
