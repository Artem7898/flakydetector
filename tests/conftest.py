"""Pytest configuration and fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def flaky_samples_dir() -> Path:
    """Path to flaky test samples directory."""
    return Path(__file__).parent / "flaky_samples"


@pytest.fixture
def async_flaky_source(flaky_samples_dir: Path) -> str:
    """Load async flaky test source."""
    return (flaky_samples_dir / "async_flaky.py").read_text()


@pytest.fixture
def timing_flaky_source(flaky_samples_dir: Path) -> str:
    """Load timing flaky test source."""
    return (flaky_samples_dir / "timing_flaky.py").read_text()


@pytest.fixture
def sample_ci_log() -> str:
    """Sample CI log with flaky indicators."""
    return """
2024-01-15 10:23:45 [INFO] Running pytest tests/test_api.py
2024-01-15 10:23:46 [FAILED] test_api.py::test_create_user - AssertionError
2024-01-15 10:23:47 [ERROR] Connection refused: postgresql://localhost:5432/test_db
2024-01-15 10:23:48 [WARNING] Port 8080 already in use
2024-01-15 10:23:49 [INFO] Retrying test_create_user (attempt 2)
2024-01-15 10:23:50 [PASSED] test_api.py::test_create_user
2024-01-15 10:24:00 [ERROR] timeout after 30s waiting for response
"""


@pytest.fixture
def ast_analyzer() -> Any:
    """AST analyzer instance."""
    from flakydetector.analyzer.ast_analyzer import ASTAnalyzer
    return ASTAnalyzer()


@pytest.fixture
def log_analyzer() -> Any:
    """Log analyzer instance."""
    from flakydetector.analyzer.log_analyzer import LogAnalyzer
    return LogAnalyzer()


@pytest.fixture
def feature_extractor() -> Any:
    """Feature extractor instance."""
    from flakydetector.classifier.feature_extractor import FeatureExtractor
    return FeatureExtractor()