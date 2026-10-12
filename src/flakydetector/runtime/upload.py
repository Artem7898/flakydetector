"""Explicit metadata-only event upload; redirects never forward credentials."""

from __future__ import annotations

import json
import urllib.request
from typing import Any, NoReturn
from urllib.parse import urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from flakydetector.runtime.store import EvidenceStore


class UploadReceipt(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    added: int = Field(ge=0)
    duplicates: int = Field(ge=0)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> NoReturn:
        raise ValueError("Redirected event uploads are not supported")


def upload_events(
    store: EvidenceStore,
    *,
    workspace: str,
    repo: str,
    url: str,
    token: str,
    allow_remote: bool = False,
    batch_size: int = 500,
) -> dict[str, int]:
    parsed = urlsplit(url)
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use a service base URL without embedded credentials or query")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("HTTP service URL required")
    if not local and (not allow_remote or parsed.scheme != "https" or (not token)):
        raise ValueError("Remote upload requires HTTPS, a token and explicit --allow-remote")
    if not 1 <= batch_size <= 2000:
        raise ValueError("Batch size must be between 1 and 2000")
    added = duplicates = 0
    cursor: int | None = 0
    opener = urllib.request.build_opener(NoRedirect)
    while cursor is not None:
        page, cursor = store.page(workspace=workspace, repo=repo, cursor=cursor, limit=batch_size)
        if not page:
            break
        body = json.dumps(
            {
                "events": [
                    event.model_copy(update={"traceback": None}).model_dump(mode="json")
                    for event in page
                ],
            },
        ).encode()
        if len(body) > 8000000:
            raise ValueError("Metadata upload exceeds 8 MB; reduce --batch-size")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(
            url.rstrip("/") + "/api/v1/events?" + urlencode({"workspace": workspace}),
            data=body,
            headers=headers,
            method="POST",
        )
        with opener.open(request, timeout=30) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("Upload receipt exceeded its byte budget")
        receipt = UploadReceipt.model_validate_json(raw)
        if receipt.added + receipt.duplicates != len(page):
            raise ValueError("Upload receipt does not account for every submitted event")
        added += receipt.added
        duplicates += receipt.duplicates
    return {"added": added, "duplicates": duplicates}
