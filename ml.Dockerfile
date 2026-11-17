# syntax=docker/dockerfile:1.7
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package gifts-ml --no-dev
ENV PATH="/app/.venv/bin:$PATH"
# TODO: implement layer caching later
ENTRYPOINT ["python", "-m", "gifts_ml.train"] 