from __future__ import annotations

import io
import zipfile

import httpx
import pytest

from flakydetector.dataset.github_collector import GitHubCollector


@pytest.mark.asyncio
async def test_github_nested_shape_redirect_and_auth_boundary():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("job.txt", "test_a.py::test_a timeout after 1s")
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path.endswith("/runs"):
            return httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "repository": {"full_name": "owner/repo"},
                            "status": "completed",
                            "conclusion": "failure",
                            "html_url": "https://github.com/owner/repo/actions/runs/42",
                        }
                    ]
                },
            )
        if request.url.host == "api.github.com":
            return httpx.Response(302, headers={"Location": "https://logs.example.test/signed"})
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, content=buffer.getvalue())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        collector = GitHubCollector("unit-test-only", client=client)
        (run,) = await collector.get_failed_runs("owner/repo")
        assert run.run_id == 42 and run.repository == "owner/repo"
        assert await collector.extract_anomalies_from_run("owner/repo", 42)
        assert len(requests) == 3


@pytest.mark.asyncio
async def test_github_errors_do_not_become_empty_success():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(403))
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await GitHubCollector("unit-test-only", client=client).get_failed_runs("owner/repo")
