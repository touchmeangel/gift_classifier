# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1

COPY pyproject.toml uv.lock ./
COPY packages/gifts-collect/pyproject.toml packages/gifts-collect/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package gifts-collect --no-install-workspace

COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package gifts-collect


FROM python:3.11-slim AS runtime

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/packages/gifts-collect /app/packages/gifts-collect

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

CMD ["python", "-m", "gifts_collect"]
