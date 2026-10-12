"""Secure composition root: scoped access, no-store responses and killable workers."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from flakydetector import __version__
from flakydetector.security.auth import (
    SCOPES,
    Credential,
    Principal,
    authenticate,
    is_loopback,
    load_credentials,
)
from flakydetector.utils.config import Settings
from flakydetector.workers.supervisor import (
    ProcessSupervisor,
    WorkerBusy,
    WorkerFailure,
    WorkerTimeout,
)


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = (app, max_bytes)

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
                        scope,
                        receive,
                        send,
                    )
                    return
                if not message.get("more_body", False):
                    break
        pending = iter(messages)

        async def replay() -> Message:
            message = next(pending, None)
            return message if message is not None else await receive()

        await self.app(scope, replay, send)


@dataclass(slots=True)
class ApplicationContext:
    settings: Settings
    supervisor: ProcessSupervisor
    credentials: tuple[Credential, ...]
    source_signing_key: bytes = field(default_factory=lambda: secrets.token_bytes(32), repr=False)

    async def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self.supervisor.run({"operation": "analyze", **payload})
        except WorkerBusy as exc:
            raise HTTPException(503, str(exc)) from None
        except WorkerTimeout as exc:
            raise HTTPException(504, str(exc)) from None
        except WorkerFailure:
            raise HTTPException(422, "Analysis worker could not complete this input") from None


def context(request: Request) -> ApplicationContext:
    return cast(ApplicationContext, request.app.state.context)


def require(request: Request, scope: str, workspace: str = "local") -> Principal:
    principal = cast(Principal | None, getattr(request.state, "principal", None))
    if principal is None or not principal.permits(scope, workspace):
        raise HTTPException(403, "Required capability or workspace grant is missing")
    return principal


def create_app(settings: Settings | None = None) -> FastAPI:
    options = settings or Settings.from_env()
    credentials = load_credentials(options.credentials_file)
    if options.api_token:
        credentials = (
            *credentials,
            Credential(
                hashlib.sha256(options.api_token.encode()).hexdigest(),
                Principal("operator", frozenset({"local"}), SCOPES),
            ),
        )
    if options.profile == "shared" and (not credentials):
        raise ValueError("Shared mode requires valid credentials")
    if (
        options.profile == "shared"
        and len(
            {
                workspace
                for credential in credentials
                for workspace in credential.principal.workspaces
            }
        )
        > 1
    ):
        raise ValueError(
            "One workspace per shared instance; use separate restricted containers for independent trust domains",
        )
    ctx = ApplicationContext(options, ProcessSupervisor(options), credentials)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        yield
        await ctx.supervisor.close()

    api = FastAPI(
        title="FlakyDetector evidence and risk analysis",
        version=__version__,
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

    async def security_boundary(request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        # Local loopback trust is not a permission for DNS-rebinding Host names.
        if (
            options.profile == "local"
            and (request.url.hostname or "") != "localhost"
            and (not is_loopback(request.url.hostname or ""))
        ):
            return JSONResponse(
                {"detail": "Local profile requires a loopback Host"},
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )
        if path.startswith("/api/v1"):
            origin = request.headers.get("origin")
            if (
                origin
                and request.method not in {"GET", "HEAD", "OPTIONS"}
                and (origin not in options.cors_origins)
                and (origin.rstrip("/") != str(request.base_url).rstrip("/"))
            ):
                return JSONResponse(
                    {"detail": "Origin is not permitted"},
                    status_code=403,
                    headers={"Cache-Control": "no-store"},
                )
            peer = request.client.host if request.client else ""
            if options.profile == "local" and (not is_loopback(peer)):
                return JSONResponse(
                    {
                        "detail": "Local profile accepts loopback clients only; configure shared profile explicitly",
                    },
                    status_code=403,
                    headers={"Cache-Control": "no-store"},
                )
            if credentials:
                principal = authenticate(request.headers.get("authorization", ""), credentials)
                if principal is None:
                    return JSONResponse(
                        {"detail": "Bearer token required"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
                    )
            else:
                principal = Principal("local-operator", frozenset({"local"}), SCOPES)
            request.state.principal = principal
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    api.middleware("http")(security_boundary)

    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic error.input and ctx may contain the COMPLETE source or credentials.
        return JSONResponse(
            {
                "detail": "Request validation failed; verify the API schema. Submitted values are not echoed.",
            },
            status_code=422,
        )

    api.exception_handler(RequestValidationError)(validation_error)

    async def safe_value_error(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            {"detail": "Input violates a validation or policy constraint."}, status_code=422
        )

    api.exception_handler(ValueError)(safe_value_error)

    from flakydetector.dashboard.routes import router

    api.include_router(router, prefix="/api/v1")

    def health() -> dict[str, str]:
        return {"status": "alive", "version": __version__}

    api.get("/health")(health)

    def ready() -> JSONResponse:
        # Model loading happens in bounded child workers. Readiness is core availability,
        # not an unexecuted claim that optional model artifacts were validated.
        return JSONResponse(
            {
                "status": "ready",
                "model": "configured-not-prevalidated" if options.model_path else "disabled",
                "source_mode": options.source_mode,
            },
        )

    api.get("/ready")(ready)

    static = Path(__file__).parent / "static"
    if static.is_dir():
        api.mount("/", StaticFiles(directory=static, html=True), name="dashboard")
    return api


app = create_app()
