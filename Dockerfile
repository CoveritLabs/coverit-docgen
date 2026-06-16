# Builder
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev

# Runtime
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"
ENV ENVIRONMENT=production
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN playwright install --with-deps chromium && \
    mkdir -p /app/logs && \
    useradd -m docgen && \
    chown -R docgen:docgen /app /ms-playwright

COPY --chown=docgen:docgen src ./src

USER docgen

CMD ["arq", "src.worker.WorkerSettings"]
