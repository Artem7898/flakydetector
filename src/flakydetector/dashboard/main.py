"""FastAPI application for FlakyDetector dashboard."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from flakydetector.dashboard.models import (
    AnalysisRequest,
    AnalysisResponse,
    FeatureImportanceResponse,
    HealthResponse,
    RepositoryStatsResponse,
)
from flakydetector.dashboard.routes import router as api_router
from flakydetector.utils.config import get_settings
from flakydetector.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Application lifespan handler."""
    settings = get_settings()
    setup_logging(settings.log_level)

    logger.info(
        "application_starting",
        version="0.1.0",
        debug=settings.dashboard.debug,
    )

    yield

    logger.info("application_stopping")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="FlakyDetector API",
        description="Scientific-grade flaky test detection system",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.dashboard.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(api_router, prefix="/api/v1")

    # Static files for React build (if exists)
    static_dir = Path(__file__).parent.parent.parent.parent / "dashboard_frontend" / "build"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="healthy", version="0.1.0")


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "flakydetector.dashboard.main:app",
        host=settings.dashboard.host,
        port=settings.dashboard.port,
        reload=settings.dashboard.debug,
    )