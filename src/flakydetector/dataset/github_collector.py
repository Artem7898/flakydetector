"""Adapter for collecting CI logs from GitHub Actions."""

from __future__ import annotations

import io
import zipfile
from typing import Any, AsyncIterator

import httpx
from pydantic import BaseModel, Field

from flakydetector.analyzer.log_analyzer import LogAnalyzer
from flakydetector.models.domain import LogAnomaly
from flakydetector.utils.logger import get_logger

logger = get_logger(__name__)


class GitHubRunInfo(BaseModel):
    """Parsed information about a GitHub Actions run."""
    run_id: int
    repository: str
    status: str
    conclusion: str | None
    html_url: str


class GitHubCollector:
    """Fetches and parses CI logs from GitHub API."""

    def __init__(self, token: str, log_analyzer: LogAnalyzer | None = None) -> None:
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30.0,
        )
        self._log_analyzer = log_analyzer or LogAnalyzer()

    async def get_failed_runs(
            self, repo: str, per_page: int = 10
    ) -> list[GitHubRunInfo]:
        """Fetch recent failed workflow runs."""
        url = f"https://api.github.com/repos/{repo}/actions/runs"
        params = {"status": "failure", "per_page": per_page}

        response = await self._client.get(url, params=params)
        response.raise_for_status()

        runs = []
        for item in response.json().get("workflow_runs", []):
            runs.append(GitHubRunInfo(**item))

        logger.info("github_failed_runs_fetched", repo=repo, count=len(runs))
        return runs

    async def extract_anomalies_from_run(
            self, repo: str, run_id: int
    ) -> list[LogAnomaly]:
        """Download logs for a specific run and analyze them."""
        url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/logs"

        try:
            response = await self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning("github_logs_unavailable", run_id=run_id, error=str(e))
            return []

        # GitHub returns logs as a ZIP archive
        anomalies: list[LogAnomaly] = []
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            for file in z.namelist():
                if file.endswith(".txt"):
                    log_content = z.read(file).decode("utf-8", errors="replace")
                    # Delegate parsing to our Core Domain
                    anomalies.extend(self._log_analyzer.analyze_log(log_content))

        logger.info("github_run_analyzed", run_id=run_id, anomalies=len(anomalies))
        return anomalies

    async def close(self) -> None:
        await self._client.aclose()