"""Trusted-base debt policy. Partial scans never establish resolution."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from flakydetector.models.domain import (
    SEVERITY_RANK,
    AnalysisResponse,
    FlakySeverity,
    StaticFinding,
    ValueModel,
)
from flakydetector.reporting.catalog import FINGERPRINT_VERSION, RULESET_VERSION


class Baseline(ValueModel):
    schema_version: Literal["1"] = "1"
    ruleset_version: str = RULESET_VERSION
    fingerprint_version: str = FINGERPRINT_VERSION
    revision: str = Field(min_length=7, max_length=64)
    scope: str = Field(min_length=1)
    accepted_by: str = Field(min_length=1, max_length=200)
    findings: tuple[StaticFinding, ...]


def create_baseline(
    response: AnalysisResponse, *, revision: str, scope: str, accepted_by: str
) -> Baseline:
    if response.status != "ok":
        raise ValueError("Incomplete analysis cannot be accepted as a baseline")
    return Baseline(
        revision=revision, scope=scope, accepted_by=accepted_by, findings=response.findings
    )


def compare(
    response: AnalysisResponse, baseline: Baseline, *, expected_revision: str, scope: str
) -> tuple[AnalysisResponse, tuple[StaticFinding, ...]]:
    if baseline.revision != expected_revision or baseline.scope != scope:
        raise ValueError("Baseline revision or scan scope does not match the trusted base")
    if (
        baseline.ruleset_version != RULESET_VERSION
        or baseline.fingerprint_version != FINGERPRINT_VERSION
    ):
        raise ValueError("Baseline requires explicit migration/review for this ruleset")
    old = {f.finding_id: f for f in baseline.findings}
    if len(old) != len(baseline.findings):
        raise ValueError("Duplicate baseline identity")
    updated: list[StaticFinding] = []
    seen: set[str] = set()
    for finding in response.findings:
        previous = old.get(finding.finding_id)
        state = (
            "new"
            if previous is None
            else "worsened"
            if SEVERITY_RANK[finding.severity] > SEVERITY_RANK[previous.severity]
            else "existing"
        )
        updated.append(finding.model_copy(update={"baseline_state": state}))
        seen.add(finding.finding_id)
    absent = tuple(
        (
            f.model_copy(
                update={
                    "baseline_state": "resolved" if response.status == "ok" else "inconclusive"
                },
            )
            for id_, f in old.items()
            if id_ not in seen
        ),
    )
    return (response.model_copy(update={"findings": tuple(updated)}), absent)


def policy_exit(
    response: AnalysisResponse, *, fail_on: str = "high", new_only: bool = False
) -> int:
    if response.status != "ok":
        return 2
    if fail_on == "none":
        return 0
    rank = SEVERITY_RANK[FlakySeverity(fail_on)]
    return int(
        any(
            (
                SEVERITY_RANK[f.severity] >= rank
                and (not new_only or f.baseline_state in {"new", "worsened"})
                for f in response.findings
            ),
        ),
    )
