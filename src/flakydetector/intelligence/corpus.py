"""Independent review boundary for a static corpus. Never generate truth from findings."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Literal, TypedDict

from pydantic import Field, model_validator

from flakydetector.application import AnalyzeService
from flakydetector.models.domain import ValueModel
from flakydetector.reporting.catalog import RULESET_VERSION
from flakydetector.reporting.findings import digest


class EvaluationRow(TypedDict):
    case_id: str
    repo: str
    split: str
    expected: bool
    detected: bool
    analysis_complete: bool


class CorpusCase(ValueModel):
    id: str = Field(min_length=1, max_length=128)
    repository: str = Field(min_length=1, max_length=256)
    revision: str = Field(min_length=7, max_length=64)
    template_group: str = Field(min_length=1, max_length=128)
    split: Literal["train", "validation", "test"]
    file_path: str
    source: str = Field(max_length=1000000)
    source_hash: str = Field(pattern="^[a-f0-9]{64}$")
    rule_id: str
    expected_static_risk: bool
    observed_behavior: Literal[
        "unknown", "intermittent", "all_observed_passed", "always_failed"
    ] = "unknown"
    root_cause_status: Literal["unknown", "hypothesis", "confirmed"] = "unknown"
    root_cause: str | None = None
    reviewer: str = ""
    review_note: str = ""
    independently_reviewed: bool = False

    @model_validator(mode="after")
    def source_matches(self) -> CorpusCase:
        if hashlib.sha256(self.source.encode()).hexdigest() != self.source_hash:
            raise ValueError("Source hash mismatch")
        if self.root_cause_status == "confirmed" and (not self.root_cause):
            raise ValueError("Confirmed causes need independent evidence")
        return self


def evaluate_corpus(cases: Sequence[CorpusCase], *, independent: bool = True) -> dict[str, object]:
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("Corpus must be nonempty with unique case IDs")
    if independent and any(
        (
            not case.independently_reviewed or not case.reviewer or (not case.review_note)
            for case in cases
        ),
    ):
        raise ValueError("Independent review is missing; do not manufacture reviewed labels")
    if independent:
        for field in ("repository", "template_group", "source_hash"):
            owners: dict[str, str] = {}
            for case in cases:
                identity = str(getattr(case, field))
                if identity in owners and owners[identity] != case.split:
                    raise ValueError(f"{field} leakage across splits")
                owners[identity] = case.split
    evaluated: list[EvaluationRow] = []
    for case in cases:
        analysis = AnalyzeService().analyze({case.file_path: case.source})
        actual = any(finding.rule_id == case.rule_id for finding in analysis.findings)
        evaluated.append(
            {
                "case_id": case.id,
                "repo": case.repository,
                "split": case.split,
                "expected": case.expected_static_risk,
                "detected": actual,
                "analysis_complete": analysis.status == "ok",
            },
        )
    test = [row for row in evaluated if row["split"] == "test"]
    if not test:
        raise ValueError("A held-out test split is required")
    tp = sum(row["detected"] and row["expected"] for row in test)
    fp = sum(row["detected"] and (not row["expected"]) for row in test)
    fn = sum(not row["detected"] and row["expected"] for row in test)
    complete = all(row["analysis_complete"] for row in test)
    return {
        "schema_version": "1",
        "ruleset_version": RULESET_VERSION,
        "dataset_hash": digest([case.model_dump(mode="json") for case in cases]),
        "independent_review_attested": independent,
        "evaluation_kind": "reviewed_static_corpus" if independent else "synthetic_regression_only",
        "heldout_cases": len(test),
        "analysis_coverage": sum(row["analysis_complete"] for row in test) / len(test),
        "precision": tp / (tp + fp) if complete and tp + fp else None,
        "recall": tp / (tp + fn) if complete and tp + fn else None,
        "results": evaluated,
        "limitations": [
            "Review flags are reviewer attestations, not automatically verified scientific independence.",
            "This evaluates static-rule agreement, not runtime flakiness or calibrated probability.",
            "Incomplete cases stay in coverage; aggregate accuracy is withheld when heldout analysis is incomplete.",
            "Repository-cluster intervals and external replication remain separate review requirements.",
        ],
    }
