"""Conservative change impact. Never authorizes skipping runtime regression tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from flakydetector.application import AnalyzeService


def impact_report(sources: Mapping[str, str], changed: Sequence[str]) -> dict[str, Any]:
    response = AnalyzeService().analyze(sources)
    changes = set(changed)
    affected: list[dict[str, Any]] = []
    broad = response.status != "ok" or any(path not in sources for path in changes)
    reasons = (
        [
            "Unsupported/deleted/non-test dependency changed: fall back to all static test candidates."
        ]
        if broad
        else []
    )
    for result in response.results:
        if result.result_kind != "test_candidate":
            continue
        edges: list[dict[str, str]] = []
        if broad:
            edges.append({"kind": "conservative_fallback", "path": result.file_path})
        if result.file_path in changes:
            edges.append({"kind": "changed_test_file", "path": result.file_path})
        for fixture in result.fixtures:
            if fixture.file_path in changes:
                edges.append(
                    {
                        "kind": "fixture_dependency",
                        "path": fixture.file_path,
                        "fixture": fixture.fixture_name,
                    },
                )
        if edges:
            affected.append(
                {"nodeid": result.file_path + "::" + result.test_name, "reasons": edges}
            )
    return {
        "schema_version": "1",
        "analysis_status": response.status,
        "scope": "static candidates and resolved fixture dependencies",
        "affected": affected,
        "full_scan_recommended": broad,
        "runtime_skip_safe": False,
        "limitations": reasons
        + [
            "Dynamic helper/plugin dependencies are not a complete call graph. Retain periodic full analysis.",
        ],
    }
