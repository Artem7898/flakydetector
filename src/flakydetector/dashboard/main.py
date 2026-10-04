"""Composition root: bounded workers and explicit optional-model readiness."""

from __future__ import annotations

import asyncio
import hmac
import threading
from collections.abc import AsyncGenerator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar, cast

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from flakydetector.application import AnalyzeService
from flakydetector.classifier.catboost_model import FlakyClassifier, ModelUnavailable
from flakydetector.utils.config import Settings

T = TypeVar("T")


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        messages: list[Message] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.disconnect":
                break
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    await JSONResponse({"detail": "Request byte limit exceeded"}, status_code=413)(
                        scope, receive, send
                    )
                    return
                if not message.get("more_body", False):
                    break
        pending = iter(messages)

        async def replay() -> Message:
            message = next(pending, None)
            return message if message is not None else await receive()

        await self.app(scope, replay, send)


@dataclass(slots=True, kw_only=True)
class ApplicationContext:
    settings: Settings
    service: AnalyzeService
    pool: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="flaky-analysis"
        )
    )
    slots: threading.BoundedSemaphore = field(default_factory=lambda: threading.BoundedSemaphore(2))
    model: FlakyClassifier | None = None

    async def run(self, work: Callable[[], T]) -> T:
        if not self.slots.acquire(blocking=False):
            raise HTTPException(503, "Analysis capacity exhausted; retry later")
        try:
            future = self.pool.submit(work)
        except RuntimeError:
            self.slots.release()
            raise HTTPException(503, "Analysis worker is shutting down") from None
        future.add_done_callback(lambda _: self.slots.release())
        try:
            # A timed-out job retains its slot until it finishes: no runaway worker queue.
            return await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(future)), timeout=self.settings.timeout_seconds
            )
        except TimeoutError:
            raise HTTPException(
                504, "Analysis deadline exceeded; no successful result is available"
            ) from None
        except ModelUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc


def context(request: Request) -> ApplicationContext:
    return cast(ApplicationContext, request.app.state.context)


def authorize(request: Request) -> None:
    token = context(request).settings.api_token
    if token and not hmac.compare_digest(
        request.headers.get("authorization", ""), f"Bearer {token}"
    ):
        raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"})


def create_app(
    settings: Settings | None = None, *, service: AnalyzeService | None = None
) -> FastAPI:
    options = settings or Settings.from_env()
    ctx = ApplicationContext(settings=options, service=service or AnalyzeService(options))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        if options.model_path is not None and service is None:
            model = FlakyClassifier()
            try:
                model.load_model(options.model_path)
            except ModelUnavailable as exc:
                ctx.service.degraded_reason = str(exc)
            else:
                ctx.model = model
                ctx.service.classifier = model
                ctx.service.model_version = model.manifest.model_version if model.manifest else None
        yield
        ctx.pool.shutdown(wait=True, cancel_futures=True)

    api = FastAPI(
        title="FlakyDetector risk analysis",
        version="0.2.1rc1",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    api.state.context = ctx
    api.add_middleware(
        CORSMiddleware,
        allow_origins=list(options.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )
    api.add_middleware(BodyLimitMiddleware, max_bytes=options.max_archive_bytes + 65536)
    # Local import avoids a composition-root / route import cycle.
    from flakydetector.dashboard.routes import router

    api.include_router(router, prefix="/api/v1", dependencies=[Depends(authorize)])

    def health() -> dict[str, str]:
        return {"status": "alive", "version": "0.2.1rc1"}

    def ready() -> JSONResponse:
        degraded = ctx.service.degraded_reason
        return JSONResponse(
            {
                "status": "degraded" if degraded else "ready",
                "model": "loaded" if ctx.service.classifier else "disabled",
                "reason": degraded,
            },
            status_code=503 if degraded else 200,
        )

    api.add_api_route("/health", health, methods=["GET"])
    api.add_api_route("/ready", ready, methods=["GET"])

    static = Path(__file__).parent / "static"
    if static.is_dir():
        api.mount("/", StaticFiles(directory=static, html=True), name="dashboard")
    return api


app = create_app()
