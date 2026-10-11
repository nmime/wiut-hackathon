FROM ghcr.io/astral-sh/uv:0.11.28 AS uv
FROM python:3.12.13-slim

COPY --from=uv /uv /uvx /usr/local/bin/
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    ML_AUDIT_PATH=/data/audit/requests.jsonl \
    ML_ENABLE_LLM=0 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev
COPY teammate_bridge ./teammate_bridge
COPY vendor ./vendor
COPY vendor-manifest.json ./
RUN groupadd --gid 10001 ml \
    && useradd --uid 10001 --gid ml --no-create-home ml \
    && mkdir -p /data/audit \
    && chown 10001:10001 /data/audit \
    && find vendor -type f -exec chmod 0444 {} +
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "teammate_bridge.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
