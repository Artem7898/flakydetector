"""API request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Application status")
    version: str = Field(..., description="Application version")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AnalysisRequest(BaseModel):
    """Request to analyze a repository or file."""

    repository_url: str | None = Field(
        None,
        description="GitHub repository URL",
        examples=["https://github.com/owner/repo"],
    )
    file_content: str | None = Field(
        None,
        description="Direct file content to analyze",
    )
    file_path: str | None = Field(
        None,
        description="Virtual file path for direct content",
    )
    log_content: str | None = Field(
        None,
        description="CI log content to analyze",
    )
    use_ml_classifier: bool = Field(
        default=True,
        description="Whether to use ML classification",
    )


class PatternInfo(BaseModel):
    """Information about a detected pattern."""

    pattern_type: str
    category: str
    severity: str
    description: str
    location: str
    code_snippet: str
    confidence: float


class TestAnalysisResult(BaseModel):
    """Analysis result for a single test."""

    test_name: str
    file_path: str
    is_flaky: bool
    flaky_probability: float
    patterns: list[PatternInfo] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    """Response from analysis endpoint."""

    analysis_id: UUID
    repository_url: str | None
    total_files_analyzed: int
    total_patterns_found: int
    flaky_tests: list[TestAnalysisResult]
    summary: dict[str, Any]


class FeatureImportanceItem(BaseModel):
    """Single feature importance entry."""
    name: str
    importance: float


class FeatureImportanceResponse(BaseModel):
    """Feature importance response."""

    features: list[FeatureImportanceItem]
    model_version: str


class RepositoryStatsResponse(BaseModel):
    """Repository statistics response."""

    repository_url: str
    total_tests: int
    flaky_count: int
    flaky_rate: float
    category_distribution: dict[str, int]
    severity_distribution: dict[str, int]
    top_patterns: list[dict[str, Any]]
    analysis_timestamp: datetime