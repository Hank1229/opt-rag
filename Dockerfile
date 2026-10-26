# API server image for Cloud Run: the FastAPI app with runtime dependencies only
# (no dev or eval groups). Settings come from env vars at run time; none are baked in.
FROM python:3.12.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1

WORKDIR /app

# Dependencies get their own layer, so a source-only change skips reinstalling them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
RUN uv sync --frozen --no-dev

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin opt-rag
USER opt-rag

EXPOSE 8080
# Cloud Run injects PORT; the shell form is needed to expand it.
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
