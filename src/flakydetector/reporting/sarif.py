"""SARIF 2.1.0 supported subset. Source-free and independent of merge policy."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from flakydetector import __version__
from flakydetector.models.domain import AnalysisResponse
from flakydetector.reporting.catalog import RULES
from flakydetector.security.privacy import safe_path

SCHEMA_URI = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
)


def to_sarif(
    response: AnalysisResponse, *, category: str = "flakydetector/static"
) -> dict[str, Any]:
    catalog = {r.id: r for r in RULES.values()}
    ids = sorted({f.rule_id for f in response.findings})
    rules: list[dict[str, Any]] = [
        {
            "id": id_,
            "name": catalog[id_].title.replace(" ", "-"),
            "shortDescription": {"text": catalog[id_].title},
            "fullDescription": {"text": catalog[id_].limitation},
            "help": {
                "text": catalog[id_].limitation
                + " Review source and reproduce with controlled provenance."
            },
            "helpUri": "https://flakydetector.readthedocs.io/en/latest/RULES.html#" + id_.lower(),
            "properties": {
                "tags": ["reliability", "test-quality"],
                "ruleVersion": catalog[id_].version,
            },
        }
        for id_ in ids
    ]
    results: list[dict[str, Any]] = []
    for finding in response.findings:
        path = safe_path(finding.location.file_path)
        results.append(
            {
                "ruleId": finding.rule_id,
                "ruleIndex": ids.index(finding.rule_id),
                "level": {"critical": "error", "high": "error", "medium": "warning", "low": "note"}[
                    finding.severity
                ],
                "message": {
                    "text": finding.title
                    + ". Static risk only; runtime flakiness and root cause are not established.",
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": quote(path, safe="/"),
                                "uriBaseId": "%SRCROOT%",
                            },
                            "region": {
                                "startLine": finding.location.line_start,
                                "endLine": max(
                                    finding.location.line_end or finding.location.line_start,
                                    finding.location.line_start,
                                ),
                            },
                        },
                    },
                ],
                "fingerprints": {"flakydetector/v1": finding.finding_id},
                "baselineState": {
                    "new": "new",
                    "existing": "unchanged",
                    "worsened": "updated",
                    "resolved": "absent",
                    "inconclusive": "unchanged",
                }[finding.baseline_state],
                "properties": {
                    "verdict": finding.verdict,
                    "sourceIncluded": False,
                    "findingId": finding.finding_id,
                },
            },
        )
    # GitHub's upload-sarif computes primaryLocationLineHash from the checkout.
    # Do not forge its algorithm; this portable identity serves other consumers.
    for result, finding in zip(results, response.findings, strict=True):
        region = result["locations"][0]["physicalLocation"]["region"]
        if finding.location.column_start is not None:
            region["startColumn"] = finding.location.column_start
        if finding.location.column_end is not None:
            region["endColumn"] = finding.location.column_end
    notifications = [
        {
            "level": "error" if d.level == "error" else "warning",
            "descriptor": {"id": d.code},
            "message": {
                "text": "Analysis coverage is incomplete; inspect the local diagnostic report."
            },
        }
        for d in response.diagnostics
    ]
    return {
        "$schema": SCHEMA_URI,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "FlakyDetector",
                        "version": __version__,
                        "informationUri": "https://github.com/Artem7898/flakydetector",
                        "rules": rules,
                    },
                },
                "automationDetails": {"id": category + "/"},
                "columnKind": "unicodeCodePoints",
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": response.status == "ok",
                        "toolExecutionNotifications": notifications,
                    },
                ],
                "properties": {
                    "analysisSchema": response.schema_version,
                    "sourceIncluded": False,
                    "scopeComplete": response.status == "ok",
                },
            },
        ],
    }
