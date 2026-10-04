"""GitHub REST adapter: schema conversion, redirects and bounded log downloads."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Self

import httpx
from pydantic import BaseModel

from flakydetector.analyzer.log_analyzer import LogAnalyzer
from flakydetector.models.domain import LogAnomaly


class GitHubRunInfo(BaseModel):
    run_id: int
    repository: str
    status: str
    conclusion: str | None
    html_url: str


class RepositoryPayload(BaseModel):
    full_name: str


class RunPayload(BaseModel):
    id: int
    repository: RepositoryPayload
    status: str
    conclusion: str | None
    html_url: str


class RunsPayload(BaseModel):
    workflow_runs: tuple[RunPayload, ...]


def validate_repo(repo: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or any(
        p in {".", ".."} for p in repo.split("/")
    ):
        raise ValueError("Expected owner/repository")
    return repo


class GitHubCollector:
    def __init__(
        self,
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        max_log_bytes: int = 20_000_000,
    ) -> None:
        self.client = client or httpx.AsyncClient(timeout=30, follow_redirects=False)
        self.owned = client is None
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.max_log_bytes = max_log_bytes

    async def get_failed_runs(
        self, repo: str, per_page: int = 10, *, page: int = 1
    ) -> list[GitHubRunInfo]:
        response = await self.client.get(
            f"https://api.github.com/repos/{validate_repo(repo)}/actions/runs",
            headers=self.headers,
            params={"status": "failure", "per_page": max(1, min(100, per_page)), "page": page},
        )
        response.raise_for_status()
        payload = RunsPayload.model_validate(response.json())
        return [
            GitHubRunInfo(
                run_id=r.id,
                repository=r.repository.full_name,
                status=r.status,
                conclusion=r.conclusion,
                html_url=r.html_url,
            )
            for r in payload.workflow_runs
        ]

    async def extract_anomalies_from_run(self, repo: str, run_id: int) -> list[LogAnomaly]:
        request = self.client.build_request(
            "GET",
            f"https://api.github.com/repos/{validate_repo(repo)}/actions/runs/{run_id}/logs",
            headers=self.headers,
        )
        response = await self.client.send(request, stream=True, follow_redirects=False)
        try:
            for _ in range(3):
                if response.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = response.headers.get("location")
                if not location or httpx.URL(location).scheme != "https":
                    raise ValueError("Missing or unsafe GitHub log redirect")
                await response.aclose()
                request = self.client.build_request("GET", location)
                request.headers.pop("authorization", None)
                request.headers.pop("cookie", None)
                response = await self.client.send(request, stream=True, follow_redirects=False)
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > self.max_log_bytes:
                    raise ValueError("Log archive byte limit exceeded")
        finally:
            await response.aclose()
        anomalies: list[LogAnomaly] = []
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 500 or sum(i.file_size for i in infos) > self.max_log_bytes:
                raise ValueError("Expanded log limit exceeded")
            for info in infos:
                if info.filename.endswith(".txt"):
                    if info.file_size / max(1, info.compress_size) > 100:
                        raise ValueError("Log compression ratio limit exceeded")
                    anomalies.extend(LogAnalyzer().analyze_log(archive.read(info).decode("utf-8")))
        return anomalies

    async def close(self) -> None:
        if self.owned:
            await self.client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
