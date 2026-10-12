"""Ephemeral server signatures bind source export to an unmodified, expiring response.

No source is persisted. Restarting the server invalidates outstanding grants. A downloaded
copy cannot be revoked: this authorizes a new server operation, not DRM on past exports.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from flakydetector.models.domain import AnalysisResponse


def _message(response: AnalysisResponse, subject: str) -> bytes:
    return json.dumps(
        {
            "subject": subject,
            "response": response.model_dump(mode="json", exclude={"source_grant"}),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode(
        "utf-8",
    )


def issue_source_grant(response: AnalysisResponse, *, subject: str, key: bytes) -> AnalysisResponse:
    if response.source_access != "redacted" or response.source_expires_at is None:
        return response.model_copy(update={"source_grant": None})
    return response.model_copy(
        update={
            "source_grant": hmac.new(key, _message(response, subject), hashlib.sha256).hexdigest()
        },
    )


def verify_source_grant(response: AnalysisResponse, *, subject: str, key: bytes) -> bool:
    supplied = response.source_grant
    if supplied is None:
        return False
    expected = hmac.new(key, _message(response, subject), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)
