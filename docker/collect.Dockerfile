# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./
COPY packages/common/pyproject.toml packages/common/pyproject.toml
COPY packages/collect/pyproject.toml packages/collect/pyproject.toml
COPY packages/ml/pyproject.toml packages/ml/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --package gifts-collect --no-install-workspace

COPY packages/common packages/common
COPY packages/collect packages/collect

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --package gifts-collect

FROM python:3.11-slim

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /app/.venv /app/.venv

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data /app/sessions \
    && chown appuser:appuser /app/data /app/sessions

USER appuser

ENTRYPOINT ["gifts-collect"]
CMD ["run", "--interval", "300"]