"""Explicit publishing adapter; never called automatically during analysis."""

from __future__ import annotations

import httpx

from flakydetector.dataset.github_collector import validate_repo
from flakydetector.models.domain import AnalysisResponse


def markdown_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ").replace("`", "'")


class GitHubActionsIntegration:
    def __init__(self, token: str, *, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or httpx.AsyncClient(timeout=30)
        self.owned = client is None
        self.token = token

    def format_report(self, analysis: AnalysisResponse) -> str:
        rows = [
            "### FlakyDetector static risk analysis",
            f"Status: {analysis.status}",
            "| Test | Verdict | Findings |",
            "|---|---|---|",
        ]
        rows.extend(
            f"| {markdown_cell(r.file_path + '::' + r.test_name)} | {r.verdict} | {len(r.patterns)} |"
            for r in analysis.results[:50]
        )
        rows.append("Static findings are risk indicators, not proof of observed nondeterminism.")
        return "\n".join(rows)

    async def post_pr_comment(self, repo: str, pr_number: int, analysis: AnalysisResponse) -> None:
        response = await self.client.post(
            f"https://api.github.com/repos/{validate_repo(repo)}/issues/{pr_number}/comments",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
            },
            json={"body": self.format_report(analysis)},
        )
        response.raise_for_status()

    async def close(self) -> None:
        if self.owned:
            await self.client.aclose()
