
# Docker-инфраструктура (Production-ready)
# `Dockerfile` Используем **мультистейдж сборку** и `uv` (в 10-100 раз быстрее pip, детерминированная сборка — критично для воспроизводимости науки).


# --- Stage 1: Dependencies (Cached heavily) ---
FROM python:3.12-slim AS builder

# Install uv globally
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Copy only dependency manifests to leverage Docker cache
COPY pyproject.toml ./

# Install dependencies into a virtual environment
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --no-cache-dir -e ".[dev]"

# --- Stage 2: Final Image (Minimal size) ---
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy the pre-built virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source code
COPY src/ ./src/
COPY scripts/ ./scripts/

# Create non-root user for security
RUN useradd --create-home appuser
USER appuser

# Expose port
EXPOSE 8000

# Run using uvicorn for production performance
CMD ["uvicorn", "flakydetector.dashboard.main:app", "--host", "0.0.0.0", "--port", "8000"]