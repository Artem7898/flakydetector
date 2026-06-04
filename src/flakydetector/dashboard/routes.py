"""API routes for FlakyDetector."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4
import zipfile
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Query

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
import chromadb
from flakydetector.dashboard.models import RAGSearchResponse, SimilarTestResult


logger = get_logger(__name__)
router = APIRouter()

# Singleton instances
_ast_analyzer = ASTAnalyzer()
_log_analyzer = LogAnalyzer()
_feature_extractor = FeatureExtractor(_ast_analyzer, _log_analyzer)
_classifier = FlakyClassifier()

# Safe model loading with dimension mismatch protection
_MODEL_PATH = Path("data/models/flaky_v2_42d.cbm")
if _MODEL_PATH.exists():
    try:
        _classifier.load_model(_MODEL_PATH)
    except Exception:
        logger.warning("model_dimension_mismatch", msg="Old model loaded, switching to heuristic mode. Run train_model.py!")
        _classifier = FlakyClassifier()


def _get_recommendations(
    category: FlakyCategory,
    patterns: list[Any],
) -> list[str]:
    """Generate fix recommendations based on detected patterns."""
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

    for pattern in patterns:
        if pattern.pattern_type == "network_call" and "mock" not in str(pattern.code_snippet).lower():
            recommendations.append(f"Add @patch decorator for {pattern.metadata.get('network_call', 'network call')}")

    return recommendations[:5]


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_code(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
) -> AnalysisResponse:
    """Analyze code for flaky test patterns."""
    if not request.file_content:
        raise HTTPException(status_code=400, detail="file_content is required")

    file_path = request.file_path or "test_sample.py"

    # 1. AST & Fixture Analysis
    ast_patterns, fixtures = _ast_analyzer.analyze_source(request.file_content, file_path)

    # 2. Log Analysis (if provided)
    log_anomalies = []
    if request.log_content:
        log_anomalies = _log_analyzer.analyze_log(request.log_content)

    # 3. ML Classification or Heuristic
    is_flaky = False
    flaky_probability = 0.0
    category = FlakyCategory.UNKNOWN

    if request.use_ml_classifier and ast_patterns:
        # ПЕРЕДАЕМ fixtures В ЭКСТРАКТОР ЗДЕСЬ
        features = _feature_extractor.extract_from_patterns(
            test_name=file_path,
            file_path=file_path,
            ast_patterns=ast_patterns,
            log_anomalies=log_anomalies,
            fixtures=fixtures
        )

        if _classifier.is_trained:
            is_flaky, flaky_probability = _classifier.predict_single(features.features)
        else:
            flaky_probability = min(1.0, len(ast_patterns) * 0.3 + len(log_anomalies) * 0.4)
            is_flaky = flaky_probability >= 0.5

        if ast_patterns:
            category_counts: dict[FlakyCategory, int] = {}
            for p in ast_patterns:
                category_counts[p.category] = category_counts.get(p.category, 0) + 1
            category = max(category_counts, key=category_counts.get)  # type: ignore

    # 4. Format response for Frontend
    pattern_infos = [
        PatternInfo(
            pattern_type=p.pattern_type,
            severity=p.severity.value,
            description=p.description,
            code_snippet=p.code_snippet,
        )
        for p in ast_patterns
    ]

    recommendations = _get_recommendations(category, ast_patterns)

    test_result = TestAnalysisResult(
        test_name=file_path,
        file_path=file_path,
        is_flaky=is_flaky,
        flaky_probability=flaky_probability,
        patterns=pattern_infos,
        recommendations=recommendations,
    )

    return AnalysisResponse(
        total_files_analyzed=1,
        total_patterns_found=len(ast_patterns) + len(log_anomalies),
        flaky_tests=[test_result],
        summary={
            "flaky_rate": 1.0 if is_flaky else 0.0,
            "avg_flaky_probability": flaky_probability,
        }
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

    req = AnalysisRequest(
        file_content=content.decode("utf-8", errors="replace"),
        file_path=file.filename,
        use_ml_classifier=use_ml,
    )

    return await analyze_code(req, BackgroundTasks())


@router.get("/features/importance", response_model=FeatureImportanceResponse)
async def get_feature_importance() -> FeatureImportanceResponse:
    """Get model feature importance."""
    if not _classifier.is_trained:
        raise HTTPException(status_code=503, detail="Model not trained. Train the model first.")

    importance = _classifier.get_feature_importance()
    features = [
        {"name": name, "importance": round(imp, 4)}
        for name, imp in sorted(importance.items(), key=lambda x: -x[1])
    ]

    return FeatureImportanceResponse(features=features, model_version="0.1.0")


@router.post("/analyze/directory", response_model=AnalysisResponse)
async def analyze_directory_archive(
    file: UploadFile = File(..., description="ZIP archive of Python test files"),
) -> AnalysisResponse:
    """Scan an entire directory (uploaded as ZIP) for flaky patterns."""
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip archives are supported")

    all_results: list[TestAnalysisResult] = []
    total_patterns = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "repo"
        tmp_path.mkdir()

        with zipfile.ZipFile(file.file, 'r') as zip_ref:
            zip_ref.extractall(tmp_path)

        py_files = list(tmp_path.rglob("*.py"))

        for py_file in py_files:
            try:
                source = py_file.read_text(encoding="utf-8", errors="ignore")
                # ВНИМАНИЕ: unpack tuple here
                ast_patterns, _ = _ast_analyzer.analyze_source(source, str(py_file.relative_to(tmp_path)))

                if ast_patterns:
                    total_patterns += len(ast_patterns)
                    is_flaky = len(ast_patterns) > 0

                    all_results.append(
                        TestAnalysisResult(
                            test_name=py_file.stem,
                            file_path=str(py_file.relative_to(tmp_path)),
                            is_flaky=is_flaky,
                            flaky_probability=min(1.0, len(ast_patterns) * 0.3),
                            patterns=[
                                PatternInfo(
                                    pattern_type=p.pattern_type,
                                    category=p.category.value,
                                    severity=p.severity.value,
                                    description=p.description,
                                    location=p.location.location_string,
                                    code_snippet=p.code_snippet,
                                    confidence=p.confidence,
                                ) for p in ast_patterns
                            ]
                        )
                    )
            except Exception:
                continue

    return AnalysisResponse(
        analysis_id=uuid4(),
        repository_url=None,
        total_files_analyzed=len(py_files),
        total_patterns_found=total_patterns,
        flaky_tests=all_results,
        summary={
            "scanned_files": len(py_files),
            "affected_files": len(all_results),
        }
    )


@router.get("/stats/{repo_url:path}", response_model=RepositoryStatsResponse)
async def get_repository_stats(repo_url: str) -> RepositoryStatsResponse:
    """Get statistics for a repository (placeholder)."""
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
    return {
        "ast_patterns": {
            "async_sleep": {"category": "async_race_condition", "severity": "medium", "description": "asyncio.sleep in test"},
            "concurrent_tasks": {"category": "async_race_condition", "severity": "high", "description": "Concurrent tasks without sync"},
            "time_sleep": {"category": "timing_dependency", "severity": "medium", "description": "time.sleep in test"},
            "global_mutation": {"category": "global_state", "severity": "high", "description": "Mutation of global variable"},
            "network_call": {"category": "network_dependency", "severity": "high", "description": "Network call without mocking"},
            "datetime_now": {"category": "datetime_dependency", "severity": "medium", "description": "Non-deterministic datetime usage"},
            "float_equality": {"category": "floating_point", "severity": "medium", "description": "Direct float equality comparison"},
        },
        "log_patterns": {
            "timeout": "Timeout detected",
            "connection_error": "Network connection error",
            "port_in_use": "Port conflict",
            "race_condition": "Race condition or deadlock",
            "resource_leak": "Resource leak detected",
        },
    }



# Путь к векторной базе (туда же, куда писал скрипт build_rag.py)
RAG_DB_PATH = "data/vector_db"


@router.get("/search_similar", response_model=RAGSearchResponse, tags=["rag"])
async def search_similar_tests(
        query: str = Query(..., description="Семантический запрос (например: 'утечки памяти')")
) -> RAGSearchResponse:
    """RAG endpoint: поиск тестов с похожими причинами флакинесса."""
    try:
        client = chromadb.PersistentClient(path=RAG_DB_PATH)
        collection = client.get_or_create_collection(name="flaky_analyses")

        results = collection.query(
            query_texts=[query],
            n_results=5  # Возвращаем топ-5 похожих тестов
        )

        formatted_results = []
        # results["distances"][0] содержит массив дистанций
        for nodeid, metadata, distance in zip(
                results["ids"][0],
                results["metadatas"][0],
                results["distances"][0]
        ):
            formatted_results.append(
                SimilarTestResult(
                    nodeid=nodeid,
                    flakiness_rate=metadata.get("flakiness_rate", 0.0),
                    explanation=metadata.get("explanation", ""),
                    similarity_score=round(1 - distance, 2)  # Конвертируем дистанцию в процент сходства
                )
            )

        return RAGSearchResponse(query=query, results=formatted_results)

    except Exception as e:
        # Если БД еще не создана (пользователь не запускал build_rag.py)
        raise HTTPException(status_code=404, detail=f"RAG Database not found or error: {str(e)}")