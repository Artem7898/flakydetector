"""Execution events, comparison context and monitor observations are not static scores."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from flakydetector.models.domain import ValueModel

Outcome = Literal[
    "passed", "failed", "error", "skipped", "xfailed", "xpassed", "unknown", "incomplete", "rerun"
]


class Provenance(ValueModel):
    version: Literal[4] = 4
    source_hash: str = Field(pattern="^[a-f0-9]{64}$")
    environment_hash: str = Field(pattern="^[a-f0-9]{64}$")
    revision: str = Field(default="", max_length=64)
    dirty: bool | None = None
    recorded_context_complete: bool = False
    components: dict[str, str] = Field(default_factory=dict, max_length=32)
    experiment_id: str = Field(default="", max_length=128)
    treatment_axis: Literal["none", "order", "image"] = "none"
    treatment_value: str = Field(default="", max_length=128)


class ExecutionEvent(ValueModel):
    schema_version: Literal["1"] = "1"
    event_id: str = Field(min_length=1, max_length=128)
    workspace: str = Field(default="local", pattern="^[A-Za-z0-9_-]{1,100}$")
    repo: str = Field(min_length=1, max_length=256)
    run_id: str = Field(min_length=1, max_length=128)
    invocation_id: str = Field(min_length=1, max_length=128)
    nodeid: str = Field(min_length=1, max_length=2000)
    worker: str = Field(default="main", max_length=100)
    collector: str = Field(default="pytest", max_length=100)
    attempt: int = Field(ge=1)
    phase: Literal["setup", "call", "teardown", "session"] = "call"
    sequence: int = Field(ge=0)
    outcome: Outcome
    started_at: datetime
    ended_at: datetime
    duration: float = Field(ge=0, allow_inf_nan=False)
    expected: bool = False
    failure_kind: Literal[
        "assertion",
        "exception",
        "timeout",
        "infrastructure",
        "collection",
        "interrupted",
        "unknown",
    ] = "unknown"
    traceback: str | None = Field(default=None, max_length=8000)
    corroboration_id: str | None = Field(default=None, max_length=128)
    provenance: Provenance
    source_file_hash: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")

    @field_validator("started_at", "ended_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone-aware timestamps required")
        return value

    @model_validator(mode="after")
    def duration_order(self) -> ExecutionEvent:
        if self.ended_at < self.started_at:
            raise ValueError("Event ends before it starts")
        return self


class Attempt(ValueModel):
    repo: str
    workspace: str
    run_id: str
    invocation_id: str
    nodeid: str
    worker: str
    attempt: int
    started_at: datetime
    ended_at: datetime
    duration: float
    outcome: Outcome
    failure_kind: str
    provenance: Provenance
    event_ids: tuple[str, ...]
    complete: bool
    source_file_hash: str | None = None
    comparison_status: str = "unknown"
    comparability_reasons: tuple[str, ...] = ()


class MonitorObservation(ValueModel):
    observation_id: str
    monitor: str
    monitor_version: str = "1"
    nodeid: str
    status: Literal["detected", "not_detected", "insufficient_evidence"]
    verdict: str
    confidence: Literal["high", "medium", "low", "none"]
    evidence_ids: tuple[str, ...] = ()
    facts: tuple[str, ...] = ()
    limitations: tuple[str, ...] = (
        "Root cause and causal contribution of static findings are not established.",
    )
    metrics: dict[str, float | int | None] = Field(default_factory=dict)
