"""Unit tests for AST analyzer."""

from __future__ import annotations

from flakydetector.analyzer.ast_analyzer import ASTAnalyzer
from flakydetector.models.domain import FlakyCategory


def test_detects_time_sleep(async_flaky_source: str, ast_analyzer: ASTAnalyzer) -> None:
    """Test detection of time.sleep patterns."""
    patterns = ast_analyzer.analyze_source(async_flaky_source, "test_async.py")

    sleep_patterns = [p for p in patterns if "sleep" in p.pattern_type]
    assert len(sleep_patterns) >= 1

    for pattern in sleep_patterns:
        assert pattern.category in (
            FlakyCategory.TIMING_DEPENDENCY,
            FlakyCategory.ASYNC_RACE_CONDITION,
        )


def test_detects_async_gather(async_flaky_source: str, ast_analyzer: ASTAnalyzer) -> None:
    """Test detection of asyncio.gather patterns."""
    patterns = ast_analyzer.analyze_source(async_flaky_source, "test_async.py")

    gather_patterns = [p for p in patterns if p.pattern_type == "concurrent_tasks"]
    assert len(gather_patterns) >= 1
    assert gather_patterns[0].category == FlakyCategory.ASYNC_RACE_CONDITION


def test_detects_datetime_now(timing_flaky_source: str, ast_analyzer: ASTAnalyzer) -> None:
    """Test detection of datetime.now() patterns."""
    patterns = ast_analyzer.analyze_source(timing_flaky_source, "test_timing.py")

    datetime_patterns = [p for p in patterns if p.pattern_type == "datetime_now"]
    assert len(datetime_patterns) >= 1
    assert datetime_patterns[0].category == FlakyCategory.DATE_TIME_DEPENDENCY


def test_global_mutation_detection(ast_analyzer: ASTAnalyzer) -> None:
    """Test detection of global variable mutation."""
    source = '''
COUNTER = 0

def test_increment():
    global COUNTER
    COUNTER += 1
    assert COUNTER == 1
'''
    patterns = ast_analyzer.analyze_source(source, "test_global.py")

    mutation_patterns = [p for p in patterns if p.pattern_type == "global_mutation"]
    assert len(mutation_patterns) == 1
    assert mutation_patterns[0].metadata["variable"] == "COUNTER"


def test_network_call_detection(ast_analyzer: ASTAnalyzer) -> None:
    """Test detection of network calls without mocking."""
    source = '''
def test_api_call():
    import requests
    response = requests.get("https://api.example.com/data")
    assert response.status_code == 200
'''
    patterns = ast_analyzer.analyze_source(source, "test_network.py")

    network_patterns = [p for p in patterns if p.pattern_type == "network_call"]
    assert len(network_patterns) == 1
    assert network_patterns[0].category == FlakyCategory.NETWORK_DEPENDENCY


def test_network_call_with_mock_reduced_confidence(ast_analyzer: ASTAnalyzer) -> None:
    """Test that mocked network calls have reduced confidence."""
    source = '''
from unittest.mock import patch

@patch("requests.get")
def test_api_call(mock_get):
    mock_get.return_value.status_code = 200
    response = requests.get("https://api.example.com/data")
    assert response.status_code == 200
'''
    patterns = ast_analyzer.analyze_source(source, "test_mocked.py")

    network_patterns = [p for p in patterns if p.pattern_type == "network_call"]
    if network_patterns:
        # Should have low confidence due to mock presence
        assert network_patterns[0].confidence < 0.5


def test_float_equality_detection(ast_analyzer: ASTAnalyzer) -> None:
    """Test detection of float equality comparison."""
    source = '''
def test_float_calculation():
    result = 0.1 + 0.2
    assert result == 0.3  # Will fail due to floating point
'''
    patterns = ast_analyzer.analyze_source(source, "test_float.py")

    float_patterns = [p for p in patterns if p.pattern_type == "float_equality"]
    assert len(float_patterns) == 1
    assert float_patterns[0].confidence > 0.9


def test_file_without_context_detection(ast_analyzer: ASTAnalyzer) -> None:
    """Test detection of file operations without context manager."""
    source = '''
def test_file_read():
    f = open("test.txt")
    content = f.read()
    assert content
    f.close()
'''
    patterns = ast_analyzer.analyze_source(source, "test_file.py")

    file_patterns = [p for p in patterns if p.pattern_type == "file_without_context"]
    assert len(file_patterns) == 1


def test_file_with_context_no_false_positive(ast_analyzer: ASTAnalyzer) -> None:
    """Test that proper context manager usage doesn't trigger false positive."""
    source = '''
def test_file_read():
    with open("test.txt") as f:
        content = f.read()
        assert content
'''
    patterns = ast_analyzer.analyze_source(source, "test_file.py")

    file_patterns = [p for p in patterns if p.pattern_type == "file_without_context"]
    assert len(file_patterns) == 0