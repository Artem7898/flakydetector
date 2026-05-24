"""Core domain models for flaky test detection."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field


class FlakyCategory(str, Enum):
    """Root cause categories for flaky tests."""

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


class FlakySeverity(str, Enum):
    """Severity levels for flaky test impact."""

    LOW = "low"  # Rare failures, quick to fix
    MEDIUM = "medium"  # Occasional failures, moderate fix time
    HIGH = "high"  # Frequent failures, complex fix
    CRITICAL = "critical"  # Almost always fails, blocks CI


class TestRunStatus(str, Enum):
    """Status of a single test run."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    FLAKY_PASSED = "flaky_passed"  # Passed but showed flaky behavior
    FLAKY_FAILED = "flaky_failed"  # Failed due to flakiness


class DetectionMethod(str, Enum):
    """Method used to detect flakiness."""

    AST_PATTERN = "ast_pattern"
    LOG_ANALYSIS = "log_analysis"
    STATISTICAL = "statistical"
    ML_CLASSIFIER = "ml_classifier"
    LLM_ANALYSIS = "llm_analysis"
    ENSEMBLE = "ensemble"


class CodeLocation(BaseModel):
    """Source code location."""

    file_path: str = Field(..., description="Relative path to the file")
    line_start: int = Field(..., ge=1, description="Start line number")
    line_end: int | None = Field(default=None, ge=1, description="End line number")
    function_name: str | None = Field(default=None, description="Function/method name")
    class_name: str | None = Field(default=None, description="Class name")

    @computed_field
    @property
    def location_string(self) -> str:
        """Human-readable location string."""
        base = f"{self.file_path}:{self.line_start}"
        if self.function_name:
            base = f"{base} in {self.function_name}"
            if self.class_name:
                base = f"{base} ({self.class_name})"
        return base


class ASTPattern(BaseModel):
    """Detected AST pattern indicating potential flakiness."""

    pattern_type: str
    category: FlakyCategory
    severity: FlakySeverity
    description: str
    location: CodeLocation
    code_snippet: str
    confidence: float
    fix_suggestion: str = Field(default="", description="Actionable steps to fix the pattern")
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestRunResult(BaseModel):
    """Result of a single test execution."""

    run_id: UUID = Field(default_factory=uuid4)
    test_name: str
    status: TestRunStatus
    duration_ms: float = Field(..., ge=0.0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    error_message: str | None = None
    error_traceback: str | None = None
    ci_run_id: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)


class FlakyTestReport(BaseModel):
    """Complete analysis report for a potentially flaky test."""

    report_id: UUID = Field(default_factory=uuid4)
    test_name: str
    file_path: str
    is_flaky: bool
    flaky_probability: float = Field(..., ge=0.0, le=1.0)
    category: FlakyCategory
    severity: FlakySeverity
    detection_methods: list[DetectionMethod] = Field(default_factory=list)
    patterns: list[ASTPattern] = Field(default_factory=list)
    test_runs: list[TestRunResult] = Field(default_factory=list)

    @computed_field
    @property
    def flaky_rate(self) -> float:
        """Calculate flaky rate from test runs."""
        if not self.test_runs:
            return 0.0
        flaky_count = sum(
            1 for r in self.test_runs
            if r.status in (TestRunStatus.FLAKY_PASSED, TestRunStatus.FLAKY_FAILED)
        )
        return flaky_count / len(self.test_runs)

    @computed_field
    @property
    def avg_duration_ms(self) -> float:
        """Average test duration."""
        if not self.test_runs:
            return 0.0
        return sum(r.duration_ms for r in self.test_runs) / len(self.test_runs)

    @computed_field
    @property
    def duration_variance_ms(self) -> float:
        """Variance in test duration (indicator of timing issues)."""
        if len(self.test_runs) < 2:
            return 0.0
        mean = self.avg_duration_ms
        return sum((r.duration_ms - mean) ** 2 for r in self.test_runs) / len(self.test_runs)


class RepositoryAnalysis(BaseModel):
    """Aggregated analysis for a repository."""

    repo_id: UUID = Field(default_factory=uuid4)
    repo_url: str
    analysis_timestamp: datetime = Field(default_factory=datetime.utcnow)
    total_tests: int = 0
    flaky_tests: list[FlakyTestReport] = Field(default_factory=list)

    @computed_field
    @property
    def flaky_rate(self) -> float:
        """Overall flaky rate."""
        if self.total_tests == 0:
            return 0.0
        return len(self.flaky_tests) / self.total_tests

    @computed_field
    @property
    def category_distribution(self) -> dict[FlakyCategory, int]:
        """Distribution of flaky categories."""
        dist: dict[FlakyCategory, int] = {}
        for report in self.flaky_tests:
            dist[report.category] = dist.get(report.category, 0) + 1
        return dist

    @computed_field
    @property
    def severity_distribution(self) -> dict[FlakySeverity, int]:
        """Distribution of severity levels."""
        dist: dict[FlakySeverity, int] = {}
        for report in self.flaky_tests:
            dist[report.severity] = dist.get(report.severity, 0) + 1
        return dist


class LogEntry(BaseModel):
    """Parsed CI log entry."""

    timestamp: datetime | None = None
    level: str = "INFO"
    message: str = ""
    test_name: str | None = None
    file_path: str | None = None
    line_number: int | None = None
    raw_line: str = ""


class FixtureInfo(BaseModel):
    """Extracted metadata from a pytest fixture."""
    fixture_name: str = Field(default="function", description="pytest scope (function, class, module, session)")
    has_yield: bool = Field(default=False, description="True if fixture uses 'yield' (has teardown)")
    has_autouse: bool = Field(default=False, description="True if autouse=True")
    returns_mutable_literal: bool = Field(default=False, description="True if returns [], {} or set()")
    uses_finalizer: bool = Field(default=False, description="True if uses context.addfinalizer")
    line: int = Field(default=0, description="Line number")


class LogAnomaly(BaseModel):
    """Detected anomaly in CI logs."""

    anomaly_type: str
    category: FlakyCategory
    severity: FlakySeverity
    description: str
    log_entries: list[LogEntry] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FixtureInfo(BaseModel):
    """Extracted metadata from a pytest fixture."""

    fixture_name: str
    scope: str = Field(default="function", description="pytest scope (function, class, module, session)")
    has_yield: bool = Field(default=False, description="True if fixture uses 'yield' (has teardown)")
    has_autouse: bool = Field(default=False, description="True if fixture has autouse=True")
    returns_mutable_literal: bool = Field(default=False, description="True if returns [], {} or set()")
    uses_finalizer: bool = Field(default=False, description="True if uses context.addfinalizer")
    line: int = Field(default=0)