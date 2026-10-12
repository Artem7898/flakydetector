"""A single server-side projection for success, errors and explicit exports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flakydetector.models.domain import AnalysisResponse, TestAnalysisResult
from flakydetector.security.auth import Principal
from flakydetector.security.privacy import redact
from flakydetector.utils.config import Settings


def project_response(
    response: AnalysisResponse,
    settings: Settings,
    principal: Principal,
    workspace: str,
    *,
    include_source: bool = False,
) -> AnalysisResponse:

    def clean(value: str) -> str:
        return redact(value, settings.redactors)

    allowed = (
        include_source
        and settings.source_mode == "redacted"
        and principal.permits("source:read", workspace)
    )
    results: list[TestAnalysisResult] = []
    for item in response.results:
        patterns = tuple(
            (
                p.model_copy(
                    update={
                        "code_snippet": clean(p.code_snippet) if allowed else "",
                        "description": clean(p.description),
                        "fix_suggestion": clean(p.fix_suggestion),
                        "metadata": {},
                    },
                )
                for p in item.patterns
            ),
        )
        # Metadata can carry source literals; safe typed facts are in finding IR.
        anomalies = tuple(
            (
                a.model_copy(
                    update={
                        "log_entries": ()
                        if not allowed
                        else tuple(
                            (
                                e.model_copy(
                                    update={
                                        "raw_line": clean(e.raw_line),
                                        "message": clean(e.message),
                                    },
                                )
                                for e in a.log_entries
                            ),
                        ),
                        "metadata": {},
                        "description": clean(a.description),
                    },
                )
                for a in item.log_anomalies
            ),
        )
        results.append(
            item.model_copy(
                update={
                    "patterns": patterns,
                    "log_anomalies": anomalies,
                    "diagnostics": tuple(
                        (
                            d.model_copy(update={"message": clean(d.message)})
                            for d in item.diagnostics
                        ),
                    ),
                },
            ),
        )
    snapshots = (
        tuple(s.model_copy(update={"content": clean(s.content)}) for s in response.source_snapshots)
        if allowed
        else ()
    )
    # sha256 identifies ORIGINAL source. The returned content is explicitly redacted.
    return response.model_copy(
        update={
            "results": tuple(results),
            "source_snapshots": snapshots,
            "diagnostics": tuple(
                d.model_copy(update={"message": clean(d.message)}) for d in response.diagnostics
            ),
            "degraded_reason": "Optional model unavailable" if response.degraded_reason else None,
            "source_access": "redacted" if allowed else "denied" if include_source else "disabled",
            "source_expires_at": datetime.now(UTC) + timedelta(seconds=settings.source_ttl_seconds)
            if allowed
            else None,
            "source_grant": None,
            "workspace": workspace,
            "granted_scopes": tuple(sorted(principal.scopes)),
        },
    )
