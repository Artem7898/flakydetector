"""HTTP transport delegates the same prepared inputs to AnalyzeService."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile

from flakydetector.dashboard.models import AnalysisRequest
from flakydetector.input import InputError, decode, zip_bundle
from flakydetector.models.domain import AnalysisResponse

router = APIRouter()


def input_exception(exc: InputError) -> HTTPException:
    return HTTPException(413 if exc.too_large else 422, str(exc))


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_code(payload: AnalysisRequest, request: Request) -> AnalysisResponse:
    from flakydetector.dashboard.main import context

    ctx = context(request)
    result = await ctx.run(
        lambda: ctx.service.analyze(
            {payload.file_path: payload.file_content},
            log_content=payload.log_content,
            use_ml=payload.use_ml_classifier,
        )
    )
    if result.status == "error":
        raise HTTPException(422, result.model_dump(mode="json"))
    return result


@router.post("/analyze/file", response_model=AnalysisResponse)
async def analyze_file(
    request: Request, file: Annotated[UploadFile, File()], use_ml: bool = False
) -> AnalysisResponse:
    from flakydetector.dashboard.main import context

    ctx = context(request)
    try:
        if not file.filename or not file.filename.endswith(".py"):
            raise InputError("A .py file is required")
        raw = await file.read(ctx.settings.max_file_bytes + 1)
        source = decode(raw, file.filename, ctx.settings.max_file_bytes)
        if not source.strip():
            raise InputError("Empty Python source")
        return await analyze_code(
            AnalysisRequest(file_content=source, file_path=file.filename, use_ml_classifier=use_ml),
            request,
        )
    except InputError as exc:
        raise input_exception(exc) from exc
    finally:
        await file.close()


@router.post("/analyze/directory", response_model=AnalysisResponse)
async def analyze_archive(
    request: Request, file: Annotated[UploadFile, File()], use_ml: bool = False
) -> AnalysisResponse:
    from flakydetector.dashboard.main import context

    ctx = context(request)
    try:
        if not file.filename or not file.filename.endswith(".zip"):
            raise InputError("A .zip archive is required")
        raw = await file.read(ctx.settings.max_archive_bytes + 1)

        def work() -> AnalysisResponse:
            bundle = zip_bundle(raw, ctx.settings)
            return ctx.service.analyze(
                bundle.sources, diagnostics=bundle.diagnostics, use_ml=use_ml
            )

        response = await ctx.run(work)
        if response.status == "error":
            raise HTTPException(422, response.model_dump(mode="json"))
        return response
    except InputError as exc:
        raise input_exception(exc) from exc
    finally:
        await file.close()


@router.get("/features/importance")
async def feature_importance(request: Request) -> dict[str, float]:
    from flakydetector.dashboard.main import context

    ctx = context(request)
    if ctx.model is None:
        raise HTTPException(503, "No evaluated, schema-compatible model is loaded")
    return await ctx.run(ctx.model.get_feature_importance)


@router.get("/stats/{repo_url:path}")
def repository_stats(repo_url: str) -> None:
    raise HTTPException(
        501, "Repository aggregation is not implemented; use the exported execution dataset"
    )


@router.get("/search_similar")
async def search_similar(
    request: Request, query: str = Query(min_length=1, max_length=2000)
) -> object:
    from flakydetector.dashboard.main import context
    from flakydetector.rag import RagIndex, RagUnavailable

    ctx = context(request)
    path = ctx.settings.rag_path
    if path is None:
        raise HTTPException(503, "RAG is not configured")
    try:
        return await ctx.run(lambda: RagIndex(path).search(query))
    except RagUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
