"""Integration layer for posting analysis results to GitHub."""

from __future__ import annotations

import httpx

from flakydetector.models.domain import FlakyTestReport, RepositoryAnalysis
from flakydetector.utils.logger import get_logger

logger = get_logger(__name__)


class GitHubActionsIntegration:
    """Publishes FlakyDetector reports as PR comments."""

    def __init__(self, token: str) -> None:
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30.0,
        )

    def _format_report(self, analysis: RepositoryAnalysis) -> str:
        """Convert domain models to GitHub Flavored Markdown."""
        if not analysis.flaky_tests:
            return "✅ **FlakyDetector**: No flaky patterns detected."

        md = "### 🔬 FlakyDetector Analysis\n\n"
        md += f"**Flaky Rate:** `{analysis.flaky_rate:.1%}`\n\n"
        md += "| Test | File | Category | Severity | Probability |\n"
        md += "|------|------|----------|----------|-------------|\n"

        for report in analysis.flaky_tests[:10]:  # Limit to top 10 for readability
            md += (
                f"| `{report.test_name}` | `{report.file_path}` "
                f"| {report.category.value} | {report.severity.value} "
                f"| `{report.flaky_probability:.0%}` |\n"
            )

        md += "\n_*Generated automatically by FlakyDetector_*\n"
        return md

    async def post_pr_comment(
            self, repo: str, pr_number: int, analysis: RepositoryAnalysis
    ) -> bool:
        """Post analysis results as a comment on a Pull Request."""
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        body = self._format_report(analysis)

        try:
            response = await self._client.post(url, json={"body": body})
            response.raise_for_status()
            logger.info("pr_comment_posted", repo=repo, pr=pr_number)
            return True
        except httpx.HTTPStatusError as e:
            logger.error("failed_to_post_comment", error=str(e))
            return False

    async def close(self) -> None:
        await self._client.aclose()