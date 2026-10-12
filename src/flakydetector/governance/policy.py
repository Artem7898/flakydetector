"""Explicit workload policies. Missing observations are inconclusive, never perfect SLOs."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Literal

from pydantic import Field

from flakydetector.models.domain import AnalysisResponse, ValueModel
from flakydetector.reporting.baseline import policy_exit


class ReliabilityPolicy(ValueModel):
    schema_version: Literal["1"] = "1"
    static_fail_on: Literal["none", "low", "medium", "high", "critical"] = "high"
    new_only: bool = True
    max_expired_quarantine: int = Field(default=0, ge=0)
    max_first_attempt_failure_rate: float | None = Field(default=None, ge=0, le=1)
    minimum_terminal_invocations: int = Field(default=20, ge=1)
    minimum_analysis_coverage: float | None = Field(default=None, ge=0, le=1)
    minimum_reviewed_precision: float | None = Field(default=None, ge=0, le=1)
    minimum_reviewed_findings: int = Field(default=30, ge=1)


def evaluate_gates(
    policy: ReliabilityPolicy,
    metrics: Mapping[str, object],
    analysis: AnalysisResponse | None = None,
) -> dict[str, object]:
    failures: list[str] = []
    unknown: list[str] = []

    def number(key: str) -> float | None:
        value = metrics.get(key)
        if (
            key in {"first_attempt_failure_rate", "static_finding_precision"}
            and isinstance(value, (float, int))
            and (value > 1)
        ):
            return None
        return (
            float(value)
            if isinstance(value, (float, int))
            and (not isinstance(value, bool))
            and isfinite(value)
            and (value >= 0)
            else None
        )

    if analysis is not None:
        result = policy_exit(analysis, fail_on=policy.static_fail_on, new_only=policy.new_only)
        if result == 1:
            failures.append("static_risk_policy")
        elif result == 2:
            unknown.append("analysis_incomplete")
        if policy.minimum_analysis_coverage is not None:
            coverage = (
                analysis.files_parsed / analysis.files_selected if analysis.files_selected else None
            )
            if coverage is None:
                unknown.append("analysis_coverage")
            elif coverage < policy.minimum_analysis_coverage:
                failures.append("analysis_coverage")
    elif policy.minimum_analysis_coverage is not None:
        unknown.append("analysis_coverage")
    expired = number("expired_quarantine_count")
    if expired is None:
        unknown.append("expired_quarantine_count")
    elif expired > policy.max_expired_quarantine:
        failures.append("expired_quarantine_count")
    if policy.max_first_attempt_failure_rate is not None:
        exposure = number("terminal_invocations")
        rate = number("first_attempt_failure_rate")
        if exposure is None or exposure < policy.minimum_terminal_invocations or rate is None:
            unknown.append("first_attempt_failure_rate")
        elif rate > policy.max_first_attempt_failure_rate:
            failures.append("first_attempt_failure_rate")
    if policy.minimum_reviewed_precision is not None:
        exposure = number("independently_reviewed_findings")
        precision = number("static_finding_precision")
        if exposure is None or exposure < policy.minimum_reviewed_findings or precision is None:
            unknown.append("static_finding_precision")
        elif precision < policy.minimum_reviewed_precision:
            failures.append("static_finding_precision")
    return {
        "status": "inconclusive" if unknown else "failed" if failures else "passed",
        "exit_code": 2 if unknown else 1 if failures else 0,
        "violations": failures,
        "unavailable": unknown,
        "policy": policy.model_dump(mode="json"),
        "limitations": [
            "Targets are explicitly configured by the operator, not inferred industry SLOs."
        ],
    }
