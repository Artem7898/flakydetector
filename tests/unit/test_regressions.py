"""Behavioral regressions for audit F05–F16; source is analyzed, never executed."""

from __future__ import annotations

import textwrap

import pytest

from flakydetector.analyzer.ast_analyzer import ASTAnalyzer
from flakydetector.analyzer.fixture_parser import FixtureParser
from flakydetector.analyzer.log_analyzer import LogAnalyzer
from flakydetector.application import AnalyzeService
from flakydetector.classifier.feature_extractor import FeatureExtractor, FeatureInput
from flakydetector.classifier.schema import FEATURE_NAMES
from flakydetector.models.domain import TestRunStatus as RunStatus


def patterns(source):
    result = ASTAnalyzer().analyze_source(textwrap.dedent(source), "test_case.py")
    assert result.ok, result.diagnostics
    return result.patterns


@pytest.mark.parametrize(
    "prefix,call",
    [
        ("import time", "time.sleep(1)"),
        ("import time as clock", "clock.sleep(1)"),
        ("from time import sleep as wait", "wait(1)"),
        ("import asyncio as aio", "await aio.sleep(1)"),
    ],
)
def test_alias_and_async_metamorphic(prefix, call):
    hits = patterns(f"{prefix}\nasync def test_case():\n    {call}\n")
    assert len(hits) == 1
    assert hits[0].pattern_type in {"time_sleep", "async_sleep"}
    assert hits[0].location.function_name == "test_case"


def test_nested_method_not_counted_twice():
    hits = patterns("""
        import time
        class TestSuite:
            def test_case(self):
                def helper():
                    time.sleep(1)
                helper()
    """)
    assert len(hits) == 1
    assert hits[0].location.function_name == "test_case.helper"
    assert hits[0].location.class_name == "TestSuite"


@pytest.mark.parametrize(
    "header,expected",
    [
        ('with open("a") as resource:', 1),
        ("with unrelated():", 1),
        ('with open("a") as resource, open("b") as other:', 1),
    ],
)
def test_with_scope_does_not_hide_another_open(header, expected):
    hits = patterns(f'def test_case():\n    {header}\n        other_file = open("c")\n')
    assert len([p for p in hits if p.pattern_type == "file_without_context"]) == expected


@pytest.mark.parametrize("target,expected", [("requests.get", True), ("time.time", False)])
def test_patch_matches_exact_target(target, expected):
    hits = patterns(
        f'import requests\nfrom unittest.mock import patch\n@patch("{target}")\ndef test_case(mock):\n    requests.get("https://example.test")\n'
    )
    hit = next(p for p in hits if p.pattern_type == "network_call")
    assert hit.metadata["is_mocked"] is expected
    assert (hit.confidence < 0.5) is expected


def test_mock_context_does_not_leak():
    hits = patterns("""
        import requests
        from unittest.mock import patch
        def test_case():
            with patch('requests.get'):
                requests.get('url')
            requests.get('url')
    """)
    assert [p.metadata["is_mocked"] for p in hits] == [True, False]


def test_shadowed_import_not_recognized():
    assert not patterns("import time\ndef test_case(time):\n    time.sleep(1)\n")


def test_module_list_mutation_and_local_pair():
    assert any(
        p.pattern_type == "global_mutation"
        for p in patterns("STATE=[]\ndef test_case():\n    STATE.append(1)\n")
    )
    assert not patterns("STATE=[]\ndef test_case():\n    STATE=[]\n    STATE.append(1)\n")


@pytest.mark.parametrize(
    "decorator,definition",
    [
        ("from pytest import fixture as fx\n@fx", "def"),
        ("import pytest as pt\n@pt.fixture()", "async def"),
        ("import pytest_asyncio as pa\n@pa.fixture", "async def"),
    ],
)
def test_fixture_forms_and_set_factory(decorator, definition):
    (fixture,) = FixtureParser().parse_source(
        f"{decorator}\n{definition} data():\n    return set()\n", "test_case.py"
    )
    assert fixture.returns_mutable_literal
    assert fixture.fixture_name == "data"


def test_fixture_graph_uses_dependencies_not_unused_definition():
    sources = {
        "conftest.py": 'import pytest\n@pytest.fixture(scope="session")\ndef state():\n    return {}\n',
        "test_case.py": 'import pytest\n@pytest.fixture\ndef derived(state):\n    return state\n@pytest.fixture(scope="session")\ndef unused():\n    yield []\ndef test_case(derived):\n    pass\n',
    }
    response = AnalyzeService().analyze(sources)
    assert response.status == "ok"
    (result,) = response.results
    assert {f.fixture_name for f in result.fixtures} == {"derived", "state"}
    assert result.verdict == "risk_detected"
    assert not any(f.has_yield for f in result.fixtures)


def test_fixture_override_can_request_predecessor():
    response = AnalyzeService().analyze(
        {
            "conftest.py": "import pytest\n@pytest.fixture\ndef data():\n    return []\n",
            "test_case.py": "import pytest\n@pytest.fixture\ndef data(data):\n    return data\ndef test_case(data):\n    pass\n",
        }
    )
    assert response.status == "ok"
    assert len(response.results[0].fixtures) == 2


def test_fixture_cycle_explicit():
    response = AnalyzeService().analyze(
        {
            "test_case.py": "import pytest\n@pytest.fixture\ndef a(b): pass\n@pytest.fixture\ndef b(a): pass\ndef test_case(a): pass\n"
        }
    )
    assert response.status == "partial"
    assert response.results[0].verdict == "inconclusive"
    assert any(d.code == "fixture_cycle" for d in response.diagnostics)


def test_parametrized_arguments_are_not_missing_fixtures():
    response = AnalyzeService().analyze(
        {
            "test_case.py": 'import pytest as pt\n@pt.mark.parametrize("a,b", [(1,2)])\ndef test_case(a,b):\n    assert a < b\n'
        }
    )
    assert response.status == "ok"
    assert not response.results[0].fixtures


def test_clean_directory_is_successful_source_result(tmp_path):
    (tmp_path / "test_clean.py").write_text("def test_clean():\n    assert 1 == 1\n")
    (result,) = ASTAnalyzer().analyze_directory(tmp_path).values()
    assert result.ok and not result.patterns


@pytest.mark.parametrize(
    "source,code", [("def broken(:", "syntax_error"), ('x="' + "x" * 100 + '"', "file_too_large")]
)
def test_failed_parse_is_explicit(source, code):
    result = ASTAnalyzer(max_file_size=80).analyze_source(source, "test_bad.py")
    assert not result.ok
    assert result.diagnostics[0].code == code


@pytest.mark.parametrize(
    "line,status",
    [
        ("tests/test_a.py::TestCase::test_one[x] FAILED [100%]", RunStatus.FAILED),
        ("FAILED tests/test_a.py::test_one - AssertionError", RunStatus.FAILED),
        ("[ERROR] tests/test_a.py::test_one - setup", RunStatus.ERROR),
        ("tests/test_a.py::test_one SKIPPED [100%]", RunStatus.SKIPPED),
        ("tests/test_a.py::test_one XFAIL [100%]", RunStatus.XFAILED),
    ],
)
def test_log_full_nodeid_and_outcome(line, status):
    (result,) = LogAnalyzer().extract_test_results(line)
    assert result.status == status
    assert result.test_name.startswith("tests/test_a.py::")
    assert result.test_name != "tests/test_a.py"


def test_unknown_log_not_success():
    assert not LogAnalyzer().extract_test_results("tests/test_a.py::test_one collecting...")


def test_multiple_messages_do_not_count_as_multiple_runs():
    findings = LogAnalyzer().analyze_multiple_runs(
        ["timeout after 1s\ntimeout after 2s", "all quiet"]
    )
    assert findings
    assert not LogAnalyzer().analyze_multiple_runs(["timeout after 1s", "timeout after 2s"])


def test_features_filled_and_batch_preserves_used_fixtures():
    result = (
        AnalyzeService()
        .analyze(
            {
                "test_case.py": 'import pytest, time\n@pytest.fixture(scope="session",autouse=True)\ndef state():\n    yield {}\ndef test_case():\n    time.sleep(1)\n'
            },
            log_content="test_case.py::test_case FAILED - timeout after 1s",
        )
        .results[0]
    )
    vector = FeatureExtractor().extract_from_patterns(
        "test_case", "test_case.py", result.patterns, result.log_anomalies, result.fixtures
    )
    assert len(vector.features) == len(FEATURE_NAMES) == 42
    for name in [
        "ast_time_sleep",
        "ast_total_patterns",
        "log_timeout",
        "log_total_anomalies",
        "category_timing_dependency",
        "has_session_or_module_fixture",
        "has_yield_in_fixture",
        "fixture_returns_mutable",
        "fixture_has_autouse",
        "test_uses_fixtures",
    ]:
        assert vector.feature_dict[name] > 0, name
    batch = FeatureExtractor().extract_batch(
        [
            FeatureInput(
                test_name="test_case",
                file_path="test_case.py",
                ast_patterns=result.patterns,
                log_anomalies=result.log_anomalies,
                fixtures=result.fixtures,
            )
        ]
    )
    assert batch == (vector.features,)


def test_unattributed_log_and_helper_visible():
    response = AnalyzeService().analyze(
        {
            "test_a.py": 'def helper():\n    open("a")\ndef test_a(): pass',
            "test_b.py": "def test_b(): pass",
        },
        log_content="connection refused",
    )
    assert response.status == "partial"
    assert {"unattributed_log", "unattributed_helper"} <= {d.code for d in response.diagnostics}
    assert any(r.log_anomalies for r in response.results)


def test_log_preserves_class_and_parameter():
    expected = "tests/test_a.py::TestCase::test_one[x]"

    (result,) = LogAnalyzer().extract_test_results(f"{expected} FAILED [100%]")

    # The prefix will not detect the loss of a class or parameter.
    assert result.test_name == expected
    assert result.status == RunStatus.FAILED


def test_monkeypatch_scope_and_decorator_injection():
    response = AnalyzeService().analyze(
        {
            "test_a.py": 'import requests\nfrom unittest.mock import patch\n@patch("requests.get")\ndef test_a(mock):\n    requests.get("url")\ndef test_b(monkeypatch):\n    monkeypatch.setattr("requests.get", lambda x: 1)\n    requests.get("url")\n'
        }
    )
    assert response.status == "ok"
    assert all(r.verdict == "no_known_risk" for r in response.results)
    assert all(
        p.metadata["is_mocked"]
        for r in response.results
        for p in r.patterns
        if p.pattern_type == "network_call"
    )
