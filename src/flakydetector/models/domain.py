"""Validated values at system boundaries; risk is not observed nondeterminism."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field


def utc_now() -> datetime:
    return datetime.now(UTC)


class ValueModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FlakyCategory(StrEnum):
    ASYNC_RACE_CONDITION = "async_race_condition"
    TIMING_DEPENDENCY = "timing_dependency"
    GLOBAL_STATE = "global_state_mutation"
    NETWORK_DEPENDENCY = "network_dependency"
    NON_DETERMINISTIC_ORDER = "non_deterministic_order"
    RESOURCE_LEAK = "resource_leak"
    CONCURRENT_ACCESS = "concurrent_access"
    FLOATING_POINT = "floating_point_imprecision"
    DATE_TIME_DEPENDENCY = "datetime_dependency"
    FILE_SYSTEM = "file_system_dependency"
    UNKNOWN = "unknown"


class FlakySeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_RANK = {severity: rank for rank, severity in enumerate(FlakySeverity)}


class TestRunStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    XFAILED = "xfailed"
    XPASSED = "xpassed"
    UNKNOWN = "unknown"
    INCOMPLETE = "incomplete"


class DetectionMethod(StrEnum):
    AST_PATTERN = "ast_pattern"
    LOG_ANALYSIS = "log_analysis"
    ML_CLASSIFIER = "ml_classifier"
    STATISTICAL = "statistical"


class CodeLocation(ValueModel):
    file_path: str
    line_start: int = Field(ge=1)
    line_end: int | None = Field(default=None, ge=1)
    function_name: str | None = None
    class_name: str | None = None

    @computed_field
    @property
    def location_string(self) -> str:
        suffix = f" in {self.function_name}" if self.function_name else ""
        return f"{self.file_path}:{self.line_start}{suffix}"


class ASTPattern(ValueModel):
    pattern_type: str
    category: FlakyCategory
    severity: FlakySeverity
    description: str
    location: CodeLocation
    code_snippet: str
    confidence: float = Field(
        ge=0, le=1, description="Rule evidence confidence, not flake probability"
    )
    fix_suggestion: str = ""
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class FixtureInfo(ValueModel):
    fixture_name: str
    scope: str = "function"
    has_yield: bool = False
    has_autouse: bool = False
    returns_mutable_literal: bool = False
    uses_finalizer: bool = False
    line: int = 0
    file_path: str = ""
    class_name: str | None = None
    dependencies: tuple[str, ...] = ()
    function_name: str = ""


class TestDefinition(ValueModel):
    name: str
    class_name: str | None = None
    line: int
    fixtures: tuple[str, ...] = ()

    @property
    def qualified_name(self) -> str:
        return f"{self.class_name}::{self.name}" if self.class_name else self.name


class AnalysisDiagnostic(ValueModel):
    code: str
    message: str
    file_path: str = ""
    line: int | None = None
    level: Literal["warning", "error"] = "error"


class SourceAnalysis(ValueModel):
    file_path: str
    patterns: tuple[ASTPattern, ...] = ()
    fixtures: tuple[FixtureInfo, ...] = ()
    tests: tuple[TestDefinition, ...] = ()
    diagnostics: tuple[AnalysisDiagnostic, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(d.level == "error" for d in self.diagnostics)


class LogEntry(ValueModel):
    timestamp: datetime | None = None
    level: str = "UNKNOWN"
    message: str = ""
    test_name: str | None = None
    file_path: str | None = None
    line_number: int | None = None
    raw_line: str = ""


class LogAnomaly(ValueModel):
    anomaly_type: str
    category: FlakyCategory
    severity: FlakySeverity
    description: str
    log_entries: tuple[LogEntry, ...] = ()
    confidence: float = Field(ge=0, le=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class TestRunResult(ValueModel):
    run_id: UUID = Field(default_factory=uuid4)
    test_name: str
    status: TestRunStatus
    duration_ms: float = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=utc_now)


class TestAnalysisResult(ValueModel):
    result_kind: Literal["test_candidate", "module", "helper", "unattributed_log"] = (
        "test_candidate"
    )
    test_name: str
    file_path: str
    verdict: Literal["risk_detected", "no_known_risk", "inconclusive"]
    risk_score: float | None = Field(default=None, ge=0, le=1)
    patterns: tuple[ASTPattern, ...] = ()
    log_anomalies: tuple[LogAnomaly, ...] = ()
    fixtures: tuple[FixtureInfo, ...] = ()
    diagnostics: tuple[AnalysisDiagnostic, ...] = ()
    backend_used: Literal["rules", "ml"] = "rules"
    model_score: float | None = Field(default=None, ge=0, le=1)
    calibrated_probability: float | None = Field(default=None, ge=0, le=1)
    recommendations: tuple[str, ...] = ()


class SourceSnapshot(ValueModel):
    file_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: str


class AnalysisResponse(ValueModel):
    schema_version: str = "2.1.0"
    analysis_id: UUID = Field(default_factory=uuid4)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshots: tuple[SourceSnapshot, ...] = ()
    status: Literal["ok", "partial", "error"]
    # Legacy totals retained with clarified units; prefer the explicit fields below.
    total_files_analyzed: int = Field(ge=0)
    total_patterns_found: int = Field(ge=0)
    files_selected: int = Field(default=0, ge=0)
    files_parsed: int = Field(default=0, ge=0)
    files_rejected: int = Field(default=0, ge=0)
    context_files_selected: int = Field(default=0, ge=0)
    test_candidates: int = Field(default=0, ge=0)
    collected_tests: int | None = Field(default=None, ge=0)
    discovery_mode: Literal["static_default_pytest"] = "static_default_pytest"
    unique_risk_locations: int = Field(default=0, ge=0)
    tests_with_risk: int = Field(default=0, ge=0)
    evidence_links: int = Field(default=0, ge=0)
    diagnostic_groups: int = Field(default=0, ge=0)
    results: tuple[TestAnalysisResult, ...]
    diagnostics: tuple[AnalysisDiagnostic, ...] = ()
    feature_schema_version: str = "2.1.0"
    model_version: str | None = None
    degraded_reason: str | None = None
