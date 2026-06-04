"""API request/response models strictly aligned with Frontend contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AnalysisRequest(BaseModel):
    """Expected payload from React UI."""
    file_content: str | None = Field(None, description="Direct Python code string")
    file_path: str | None = Field(None, description="Virtual filename for context")
    log_content: str | None = Field(None, description="CI logs (optional)")
    use_ml_classifier: bool = Field(default=True)


class PatternInfo(BaseModel):
    """Strict mapping for React pattern card."""
    pattern_type: str
    severity: str        # Ожидает 'low', 'medium', 'high', 'critical'
    description: str
    code_snippet: str
    fix: str = Field(default="", description="How to fix this")


class TestAnalysisResult(BaseModel):
    """Strict mapping for React metrics and patterns."""
    test_name: str
    file_path: str
    is_flaky: bool
    flaky_probability: float
    patterns: list[PatternInfo] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    """Root response mapped to React state."""
    analysis_id: UUID = Field(default_factory=lambda: UUID("00000000-0000-0000-0000-000000000000"))
    repository_url: str | None = None
    total_files_analyzed: int = 1
    total_patterns_found: int = 0
    flaky_tests: list[TestAnalysisResult] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


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


class SimilarTestResult(BaseModel):
    """Результат поиска из RAG (ChromaDB)."""
    nodeid: str
    flakiness_rate: float
    explanation: str
    similarity_score: float  # ChromaDB distance (переведенный в %)

class RAGSearchResponse(BaseModel):
    """Ответ на запрос семантического поиска."""
    query: str
    results: list[SimilarTestResult]