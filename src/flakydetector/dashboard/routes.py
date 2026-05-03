"""API routes for FlakyDetector."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File

from flakydetector.analyzer.ast_analyzer import ASTAnalyzer
from flakydetector.analyzer.log_analyzer import LogAnalyzer
from flakydetector.classifier.catboost_model import FlakyClassifier
from flakydetector.classifier.feature_extractor import FeatureExtractor
from flakydetector.dashboard.models import (
    AnalysisRequest,
    AnalysisResponse,
    FeatureImportanceResponse,
    PatternInfo,
    RepositoryStatsResponse,
    TestAnalysisResult,
)
from flakydetector.models.domain import FlakyCategory, FlakySeverity
from flakydetector.utils.config import get_settings
from flakydetector.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# Singleton instances
_ast_analyzer = ASTAnalyzer()
_log_analyzer = LogAnalyzer()
_feature_extractor = FeatureExtractor(_ast_analyzer, _log_analyzer)
_classifier = FlakyClassifier()

from pathlib import Path
_MODEL_PATH = Path("data/models/flaky_v1.cbm")
if _MODEL_PATH.exists():
    _classifier.load_model(_MODEL_PATH)


def _get_recommendations(
        category: FlakyCategory,
        patterns: list[Any],
) -> list[str]:
    """Generate fix recommendations based on detected patterns."""
    recommendations: list[str] = []

    recommendation_map: dict[FlakyCategory, list[str]] = {
        FlakyCategory.ASYNC_RACE_CONDITION: [
            "Use asyncio.Event or asyncio.Condition for synchronization",
            "Consider using pytest-asyncio with proper fixture scope",
            "Add explicit wait conditions instead of time.sleep",
        ],
        FlakyCategory.TIMING_DEPENDENCY: [
            "Replace time.sleep with explicit wait conditions",
            "Use pytest-timeout with appropriate limits",
            "Mock time-dependent functions with freezegun",
        ],
        FlakyCategory.GLOBAL_STATE: [
            "Use pytest fixtures with function scope for test isolation",
            "Reset global state in setUp/tearDown methods",
            "Consider using dependency injection instead of globals",
        ],
        FlakyCategory.NETWORK_DEPENDENCY: [
            "Use responses or requests-mock for HTTP mocking",
            "Create mock servers for integration tests",
            "Implement retry logic with exponential backoff",
        ],
        FlakyCategory.NON_DETERMINISTIC_ORDER: [
            "Use sorted() for dict/set iteration in assertions",
            "Compare collections with Counter instead of direct equality",
            "Use pytest.approx for numeric comparisons",
        ],
        FlakyCategory.RESOURCE_LEAK: [
            "Use context managers (with statement) for resource handling",
            "Implement proper cleanup in pytest fixtures",
            "Use pytest-leaks plugin to detect resource leaks",
        ],
        FlakyCategory.CONCURRENT_ACCESS: [
            "Use threading.Lock or multiprocessing.Lock for shared resources",
            "Isolate database state between tests",
            "Consider using testcontainers for external dependencies",
        ],
        FlakyCategory.FLOATING_POINT: [
            "Use pytest.approx() for float comparisons",
            "Use math.isclose() with appropriate tolerances",
            "Consider using Decimal for precise calculations",
        ],
        FlakyCategory.DATE_TIME_DEPENDENCY: [
            "Use freezegun to mock datetime.now()",
            "Pass timestamp as parameter to testable functions",
            "Use factory functions for datetime creation",
        ],
        FlakyCategory.FILE_SYSTEM: [
            "Use pytest tmp_path fixture for file operations",
            "Create isolated test directories",
            "Clean up created files in teardown",
        ],
        FlakyCategory.UNKNOWN: [
            "Review test logic for implicit dependencies",
            "Add logging to identify failure patterns",
            "Run test multiple times to confirm flakiness",
        ],
    }

    recommendations = recommendation_map.get(category, [])

    # Add pattern-specific recommendations
    for pattern in patterns:
        if pattern.pattern_type == "network_call" and "mock" not in str(pattern.code_snippet).lower():
            recommendations.append(f"Add @patch decorator for {pattern.metadata.get('network_call', 'network call')}")

    return recommendations[:5]  # Limit to top 5


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_code(
        request: AnalysisRequest,
        background_tasks: BackgroundTasks,
) -> AnalysisResponse:
    """Analyze code for flaky test patterns."""
    analysis_id = uuid4()

    if not request.file_content and not request.repository_url:
        raise HTTPException(
            status_code=400,
            detail="Either file_content or repository_url must be provided",
        )

    all_results: list[TestAnalysisResult] = []
    total_patterns = 0

    if request.file_content:
        file_path = request.file_path or "test_file.py"

        # AST analysis
        ast_patterns = _ast_analyzer.analyze_source(request.file_content, file_path)
        total_patterns += len(ast_patterns)

        # Log analysis if provided
        log_anomalies = []
        if request.log_content:
            log_anomalies = _log_analyzer.analyze_log(request.log_content)
            total_patterns += len(log_anomalies)

        # ML classification if enabled
        is_flaky = False
        flaky_probability = 0.0
        category = FlakyCategory.UNKNOWN

        if request.use_ml_classifier and ast_patterns:
            features = _feature_extractor.extract_from_patterns(
                test_name=file_path,
                file_path=file_path,
                ast_patterns=ast_patterns,
                log_anomalies=log_anomalies,
            )

            # Use heuristic if model not trained
            if _classifier.is_trained:
                is_flaky, flaky_probability = _classifier.predict_single(features.features)
            else:
                flaky_probability = min(1.0, len(ast_patterns) * 0.3 + len(log_anomalies) * 0.4)
                is_flaky = flaky_probability >= 0.5

            # Determine primary category
            if ast_patterns:
                category_counts: dict[FlakyCategory, int] = {}
                for p in ast_patterns:
                    category_counts[p.category] = category_counts.get(p.category, 0) + 1
                category = max(category_counts, key=category_counts.get)  # type: ignore[arg-type]

        # Build pattern info
        pattern_infos = [
            PatternInfo(
                pattern_type=p.pattern_type,
                category=p.category.value,
                severity=p.severity.value,
                description=p.description,
                location=p.location.location_string,
                code_snippet=p.code_snippet,
                confidence=p.confidence,
            )
            for p in ast_patterns
        ]

        recommendations = _get_recommendations(category, ast_patterns)

        all_results.append(
            TestAnalysisResult(
                test_name=file_path,
                file_path=file_path,
                is_flaky=is_flaky,
                flaky_probability=flaky_probability,
                patterns=pattern_infos,
                recommendations=recommendations,
            )
        )

    return AnalysisResponse(
        analysis_id=analysis_id,
        repository_url=request.repository_url,
        total_files_analyzed=1,
        total_patterns_found=total_patterns,
        flaky_tests=all_results,
        summary={
            "flaky_rate": sum(1 for r in all_results if r.is_flaky) / max(1, len(all_results)),
            "avg_flaky_probability": sum(r.flaky_probability for r in all_results) / max(1, len(all_results)),
        },
    )


@router.post("/analyze/file")
async def analyze_uploaded_file(
        file: UploadFile = File(...),
        use_ml: bool = True,
) -> AnalysisResponse:
    """Analyze an uploaded Python file."""
    if not file.filename or not file.filename.endswith(".py"):
        raise HTTPException(status_code=400, detail="Only .py files are supported")

    content = await file.read()

    request = AnalysisRequest(
        file_content=content.decode("utf-8", errors="replace"),
        file_path=file.filename,
        use_ml_classifier=use_ml,
    )

    return await analyze_code(request, BackgroundTasks())


@router.get("/features/importance", response_model=FeatureImportanceResponse)
async def get_feature_importance() -> FeatureImportanceResponse:
    """Get model feature importance."""
    if not _classifier.is_trained:
        raise HTTPException(
            status_code=503,
            detail="Model not trained. Train the model first.",
        )

    importance = _classifier.get_feature_importance()
    features = [
        {"name": name, "importance": round(imp, 4)}
        for name, imp in sorted(importance.items(), key=lambda x: -x[1])
    ]

    return FeatureImportanceResponse(features=features, model_version="0.1.0")


@router.get("/stats/{repo_url:path}", response_model=RepositoryStatsResponse)
async def get_repository_stats(repo_url: str) -> RepositoryStatsResponse:
    """Get statistics for a repository (placeholder)."""
    # In production, this would fetch from database
    return RepositoryStatsResponse(
        repository_url=repo_url,
        total_tests=0,
        flaky_count=0,
        flaky_rate=0.0,
        category_distribution={},
        severity_distribution={},
        top_patterns=[],
        analysis_timestamp=datetime.utcnow(),
    )


@router.get("/patterns/catalog")
async def get_pattern_catalog() -> dict[str, Any]:
    """Get catalog of all detectable patterns."""
    from flakydetector.analyzer.ast_analyzer import FlakyPatternVisitor

    return {
        "ast_patterns": {
            "async_sleep": {
                "category": "async_race_condition",
                "severity": "medium",
                "description": "asyncio.sleep in test - potential race condition",
            },
            "concurrent_tasks": {
                "category": "async_race_condition",
                "severity": "high",
                "description": "Concurrent task execution without synchronization",
            },
            "time_sleep": {
                "category": "timing_dependency",
                "severity": "medium",
                "description": "time.sleep in test - timing dependency",
            },
            "global_mutation": {
                "category": "global_state",
                "severity": "high",
                "description": "Mutation of global variable",
            },
            "network_call": {
                "category": "network_dependency",
                "severity": "high",
                "description": "Network call without mocking",
            },
            "datetime_now": {
                "category": "datetime_dependency",
                "severity": "medium",
                "description": "Non-deterministic datetime usage",
            },
            "float_equality": {
                "category": "floating_point",
                "severity": "medium",
                "description": "Direct float equality comparison",
            },
        },
        "log_patterns": {
            "timeout": "Timeout detected",
            "connection_error": "Network connection error",
            "port_in_use": "Port conflict",
            "race_condition": "Race condition or deadlock",
            "resource_leak": "Resource leak detected",
        },
    }