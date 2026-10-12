"""Scoped HTTP adapters. Source-bearing data uses one explicit privacy projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import Field

from flakydetector.dashboard.models import AnalysisRequest
from flakydetector.input import InputError, decode
from flakydetector.models.domain import AnalysisResponse, ValueModel
from flakydetector.runtime.models import ExecutionEvent
from flakydetector.runtime.store import EventConflict, EvidenceStore
from flakydetector.security.grants import issue_source_grant, verify_source_grant
from flakydetector.security.privacy import safe_path
from flakydetector.security.projection import project_response

router = APIRouter()


def store(request: Request) -> EvidenceStore:
    from flakydetector.dashboard.main import context

    path = context(request).settings.evidence_db
    if path is None:
        raise HTTPException(503, "Execution history is not configured; no history is inferred")
    return EvidenceStore(path, retain_tracebacks=False)


async def analyze_sources(
    request: Request,
    sources: dict[str, str],
    *,
    workspace: str,
    include_source: bool,
    use_ml: bool,
    log: str = "",
    diagnostics: list[dict[str, Any]] | None = None,
) -> AnalysisResponse:
    from flakydetector.dashboard.main import context, require

    principal = require(request, "analyze", workspace)
    require(request, "findings:read", workspace)
    ctx = context(request)
    result = AnalysisResponse.model_validate(
        await ctx.analyze(
            {"sources": sources, "log": log, "use_ml": use_ml, "diagnostics": diagnostics or []},
        ),
    )
    projected = project_response(
        result, ctx.settings, principal, workspace, include_source=include_source
    )
    projected = issue_source_grant(projected, subject=principal.subject, key=ctx.source_signing_key)
    if projected.status == "error":
        raise HTTPException(422, projected.model_dump(mode="json"))
    return projected


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_code(
    payload: AnalysisRequest,
    request: Request,
    workspace: str = "local",
    include_source: bool = False,
) -> AnalysisResponse:
    safe_path(payload.file_path)
    return await analyze_sources(
        request,
        {payload.file_path: payload.file_content},
        workspace=workspace,
        include_source=include_source,
        use_ml=payload.use_ml_classifier,
        log=payload.log_content,
    )


@router.post("/analyze/file", response_model=AnalysisResponse)
async def analyze_file(
    request: Request,
    file: Annotated[UploadFile, File()],
    workspace: str = "local",
    include_source: bool = False,
    use_ml: bool = False,
) -> AnalysisResponse:
    from flakydetector.dashboard.main import context, require

    require(request, "analyze", workspace)
    ctx = context(request)
    try:
        name = safe_path(file.filename or "")
        if not name.lower().endswith(".py"):
            raise HTTPException(422, "A Python source file is required")
        raw = await file.read(ctx.settings.max_file_bytes + 1)
        source = decode(raw, name, ctx.settings.max_file_bytes)
        return await analyze_sources(
            request,
            {name: source},
            workspace=workspace,
            include_source=include_source,
            use_ml=use_ml,
        )
    except InputError as exc:
        raise HTTPException(
            413 if exc.too_large else 422, "Upload exceeds a supported input constraint"
        ) from None
    finally:
        await file.close()


@router.post("/analyze/directory", response_model=AnalysisResponse)
async def analyze_archive(
    request: Request,
    file: Annotated[UploadFile, File()],
    workspace: str = "local",
    include_source: bool = False,
    use_ml: bool = False,
) -> AnalysisResponse:
    from flakydetector.dashboard.main import context, require

    require(request, "analyze", workspace)
    ctx = context(request)
    try:
        if not (file.filename or "").lower().endswith(".zip"):
            raise HTTPException(422, "A ZIP archive is required")
        raw = await file.read(ctx.settings.max_archive_bytes + 1)
        # ZIP parsing/decompression belongs in the same killable child as AST work.
        import base64

        principal = require(request, "findings:read", workspace)
        result = AnalysisResponse.model_validate(
            await ctx.analyze({"archive_b64": base64.b64encode(raw).decode(), "use_ml": use_ml}),
        )
        projected = project_response(
            result, ctx.settings, principal, workspace, include_source=include_source
        )
        projected = issue_source_grant(
            projected, subject=principal.subject, key=ctx.source_signing_key
        )
        if projected.status == "error":
            raise HTTPException(422, projected.model_dump(mode="json"))
        return projected
    finally:
        await file.close()


class ExportRequest(ValueModel):
    analysis: AnalysisResponse
    include_source: bool = False
    confirm_source: bool = False
    format: str = "json"


@router.post("/export")
def export_report(payload: ExportRequest, request: Request, workspace: str = "local") -> Any:
    from flakydetector.dashboard.main import context, require

    principal = require(request, "export", workspace)
    if payload.analysis.workspace != workspace:
        raise HTTPException(403, "Workspace mismatch")
    if payload.include_source and (
        not payload.confirm_source or not principal.permits("source:read", workspace)
    ):
        raise HTTPException(403, "Source export requires source:read and explicit confirmation")
    if payload.include_source and (
        payload.analysis.source_expires_at is None
        or payload.analysis.source_expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(410, "Source view expired; reanalyze explicitly")
    if payload.include_source and (
        not verify_source_grant(
            payload.analysis,
            subject=principal.subject,
            key=context(request).source_signing_key,
        )
    ):
        raise HTTPException(
            403,
            "Source grant is missing, modified, belongs to another principal or was invalidated by a restart",
        )
    sanitized = project_response(
        payload.analysis,
        context(request).settings,
        principal,
        workspace,
        include_source=payload.include_source,
    )
    if payload.include_source:
        sanitized = sanitized.model_copy(
            update={"source_expires_at": payload.analysis.source_expires_at}
        )
    if payload.format == "sarif":
        from flakydetector.reporting.sarif import to_sarif

        return to_sarif(sanitized)
    if payload.format != "json":
        raise HTTPException(422, "Unsupported export format")
    return {
        "classification": "source-bearing-redacted"
        if sanitized.source_snapshots
        else "source-free",
        "analysis": sanitized,
    }


class EventUpload(ValueModel):
    events: tuple[ExecutionEvent, ...] = Field(max_length=2000)


@router.post("/events")
def ingest_events(
    payload: EventUpload, request: Request, workspace: str = "local"
) -> dict[str, int]:
    from flakydetector.dashboard.main import require

    require(request, "events:write", workspace)
    if any(e.collector != "pytest" or e.corroboration_id for e in payload.events):
        # Independent infrastructure confirmation is not accepted via a normal recorder key.
        raise HTTPException(
            403, "External corroboration requires a separately verified telemetry adapter"
        )
    try:
        added, duplicates = store(request).ingest(payload.events, workspace=workspace)
    except EventConflict:
        raise HTTPException(409, "Event ID conflict") from None
    return {"added": added, "duplicates": duplicates}


@router.get("/events")
def events_page(
    request: Request,
    repo: str,
    workspace: str = "local",
    cursor: int = 0,
    limit: int = Query(1000, ge=1, le=10000),
) -> dict[str, Any]:
    from flakydetector.dashboard.main import require

    principal = require(request, "events:read", workspace)
    events, next_cursor = store(request).page(
        workspace=workspace, repo=repo, cursor=cursor, limit=limit
    )
    if not principal.permits("source:read", workspace):
        events = [e.model_copy(update={"traceback": None}) for e in events]
    return {"events": events, "next_cursor": next_cursor}


@router.get("/monitors")
def monitors(request: Request, repo: str, workspace: str = "local") -> dict[str, Any]:
    from flakydetector.dashboard.main import require
    from flakydetector.runtime.monitors import MonitorEngine, attempts_from_events

    require(request, "events:read", workspace)
    events, cursor = store(request).page(workspace=workspace, repo=repo, limit=10000)
    if cursor is not None:
        raise HTTPException(413, "History exceeds replay limit; use a bounded offline evaluation")
    return {
        "schema_version": "1",
        "observations": MonitorEngine().evaluate(events),
        "attempts": attempts_from_events(events),
        "scope": "recorded comparable context; not a causal diagnosis",
    }


@router.get("/stats/{repo:path}")
def repository_stats(repo: str, request: Request, workspace: str = "local") -> dict[str, Any]:
    from flakydetector.dashboard.main import require
    from flakydetector.governance.lifecycle import LifecycleStore
    from flakydetector.governance.quarantine import QuarantineStore
    from flakydetector.intelligence.metrics import change_points, reliability_metrics

    require(request, "events:read", workspace)
    db = store(request)
    events, cursor = db.page(workspace=workspace, repo=repo, limit=10000)
    if cursor is not None:
        raise HTTPException(413, "History exceeds replay limit; select an offline window")
    return {
        "metrics": reliability_metrics(
            events,
            quarantine=QuarantineStore(db).list(workspace, repo),
            lifecycle=LifecycleStore(db).list(workspace, repo),
        ),
        "change_points": change_points(events),
    }


class QuarantineRequest(ValueModel):
    repo: str
    nodeid: str
    source_hash: str
    owner: str
    issue: str
    reason: str
    ttl_days: int = Field(default=7, ge=1, le=30)


@router.post("/quarantine")
def add_quarantine(payload: QuarantineRequest, request: Request, workspace: str = "local") -> Any:
    from flakydetector.dashboard.main import require
    from flakydetector.governance.quarantine import QuarantineEntry, QuarantineStore

    actor = require(request, "quarantine:write", workspace)
    now = datetime.now(UTC)
    entry = QuarantineEntry(
        workspace=workspace,
        approved_by=actor.subject,
        created_at=now,
        expires_at=now + timedelta(days=payload.ttl_days),
        **payload.model_dump(exclude={"ttl_days"}),
    )
    QuarantineStore(store(request)).save(entry, actor=actor.subject)
    return entry


@router.get("/quarantine")
def quarantine_list(request: Request, repo: str, workspace: str = "local") -> Any:
    from flakydetector.dashboard.main import require
    from flakydetector.governance.quarantine import QuarantineStore

    require(request, "events:read", workspace)
    return {"entries": QuarantineStore(store(request)).list(workspace, repo)}


@router.post("/lifecycle")
def append_lifecycle(
    payload: dict[str, Any], request: Request, workspace: str = "local"
) -> dict[str, bool]:
    from flakydetector.dashboard.main import require
    from flakydetector.governance.lifecycle import LifecycleEvent, LifecycleStore

    actor = require(request, "lifecycle:write", workspace)
    event = LifecycleEvent.model_validate(
        {**payload, "workspace": workspace, "actor": actor.subject}
    )
    return {"added": LifecycleStore(store(request)).append(event, actor=actor.subject)}


@router.get("/features/importance")
def feature_importance(request: Request, workspace: str = "local") -> None:
    from flakydetector.dashboard.main import require

    require(request, "findings:read", workspace)
    raise HTTPException(
        503,
        "Model diagnostics are available through the offline model evaluation report, not a shared unbounded worker",
    )


@router.get("/search_similar")
def search_similar(
    request: Request, query: str = Query(min_length=1, max_length=2000), workspace: str = "local"
) -> None:
    from flakydetector.dashboard.main import require

    require(request, "findings:read", workspace)
    raise HTTPException(
        503,
        "Shared RAG serving is disabled until workspace-isolated retrieval is configured; use the offline RAG adapter",
    )


class QuarantineUpdate(ValueModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=2000)
    ttl_days: int = Field(default=7, ge=1, le=30)


@router.post("/quarantine/{entry_id}/renew")
def renew_quarantine(
    entry_id: str, payload: QuarantineUpdate, request: Request, workspace: str = "local"
) -> Any:
    from flakydetector.dashboard.main import require
    from flakydetector.governance.quarantine import QuarantineStore

    actor = require(request, "quarantine:write", workspace)
    now = datetime.now(UTC)
    try:
        return QuarantineStore(store(request)).renew(
            workspace=workspace,
            id=entry_id,
            expected_version=payload.expected_version,
            actor=actor.subject,
            reason=payload.reason,
            expires_at=now + timedelta(days=payload.ttl_days),
            now=now,
        )
    except ValueError:
        raise HTTPException(
            409, "Quarantine update rejected; refresh its version and review the TTL"
        ) from None


@router.post("/quarantine/{entry_id}/revoke")
def revoke_quarantine(
    entry_id: str, payload: QuarantineUpdate, request: Request, workspace: str = "local"
) -> Any:
    from flakydetector.dashboard.main import require
    from flakydetector.governance.quarantine import QuarantineStore

    actor = require(request, "quarantine:write", workspace)
    try:
        return QuarantineStore(store(request)).revoke(
            workspace=workspace,
            id=entry_id,
            expected_version=payload.expected_version,
            actor=actor.subject,
            reason=payload.reason,
        )
    except ValueError:
        raise HTTPException(409, "Quarantine update rejected; refresh its version") from None


@router.get("/quarantine/{entry_id}/audit")
def quarantine_audit(entry_id: str, request: Request, workspace: str = "local") -> Any:
    import json

    from flakydetector.dashboard.main import require
    from flakydetector.governance.quarantine import QuarantineStore

    require(request, "events:read", workspace)
    qs = QuarantineStore(store(request))
    with qs.store.connection() as db:
        rows = db.execute(
            "SELECT version,actor,at,payload FROM quarantine_audit WHERE workspace=? AND entry_id=? ORDER BY version",
            (workspace, entry_id),
        ).fetchall()
    return {
        "entries": [
            {"version": row[0], "actor": row[1], "at": row[2], "entry": json.loads(row[3])}
            for row in rows
        ],
    }
