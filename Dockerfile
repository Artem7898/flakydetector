FROM node:22-bookworm-slim AS frontend
WORKDIR /ui
COPY dashboard_frontend/package*.json ./
RUN npm ci --ignore-scripts
COPY dashboard_frontend/ ./
RUN REQUIRE_RENDER_TESTS=1 npm test && npm run build

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/
COPY --from=frontend /ui/dist/ ./src/flakydetector/dashboard/static/
RUN uv sync --frozen --no-dev --extra api --no-editable

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home appuser && mkdir /app/data && chown appuser:appuser /app/data
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"
CMD ["uvicorn", "flakydetector.dashboard.main:app", "--host", "0.0.0.0", "--port", "8000"]
