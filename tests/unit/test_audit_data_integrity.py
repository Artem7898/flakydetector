"""Audit 0.2.0 F01/F02/F04/F07/F08: executable regressions, not ML benchmarks."""
from __future__ import annotations

import hashlib
import sys
from types import ModuleType
from unittest.mock import patch

import pytest

from flakydetector.application import AnalyzeService
from flakydetector.dataset.benchmark import prepare_samples, split_by_repo
from flakydetector.dataset.records import DatasetRecord
from flakydetector.pytest_flaky_trail.storage import TrailStorage


@pytest.mark.parametrize("alias", ["get", "fetch"])
@pytest.mark.parametrize("style", ["decorator", "context", "monkeypatch"])
@pytest.mark.parametrize("namespace,expected", [("requests", False), ("test_case", True)])
def test_f01_patch_targets_the_lookup_binding(alias, style, namespace, expected):
    target = f"{namespace}.{'get' if namespace == 'requests' else alias}"
    prefix = f"from requests import get as {alias}\nfrom unittest.mock import patch\n"
    body = f'{alias}("https://example.invalid")'
    if style == "decorator":
        source = prefix + f'@patch("{target}")\ndef test_case(mock_get):\n    {body}\n'
    elif style == "context":
        source = prefix + f'def test_case():\n    with patch("{target}"):\n        {body}\n'
    else:
        source = prefix + f'def test_case(monkeypatch):\n    monkeypatch.setattr("{target}", lambda url: None)\n    {body}\n'
    result = AnalyzeService().analyze({"test_case.py": source}).results[0]
    finding = next(p for p in result.patterns if p.pattern_type == "network_call")
    assert finding.metadata["is_mocked"] is expected
    assert (result.verdict == "no_known_risk") is expected


def test_f01_runtime_oracle_uses_only_a_local_fake_module():
    fake = ModuleType("audit_requests")
    calls = []
    fake.get = lambda url: calls.append(url)
    namespace = ModuleType("audit_test_case")
    with patch.dict(sys.modules, {"audit_requests": fake, "audit_test_case": namespace}):
        exec("from audit_requests import get", namespace.__dict__)
        with patch("audit_requests.get") as wrong:
            namespace.get("local-only")
            wrong.assert_not_called()
        with patch("audit_test_case.get") as correct:
            namespace.get("local-only")
            correct.assert_called_once()
    assert calls == ["local-only"]


@pytest.mark.parametrize("line", [
    "other_test.py::test_other FAILED - connection refused",
    "other/test_case.py::test_good FAILED - connection refused",
    "test_case.py::test_other FAILED - connection refused",
    "connection refused",
])
def test_f02_unmatched_logs_do_not_change_even_a_single_candidate(line):
    response = AnalyzeService().analyze(
        {"test_case.py": "def test_good(): pass\n"}, log_content=line,
    )
    test = response.results[0]
    assert test.verdict == "no_known_risk" and test.risk_score == 0
    assert not test.log_anomalies
    groups = [r for r in response.results if r.result_kind == "unattributed_log"]
    assert len(groups) == 1 and len(groups[0].log_anomalies) == 1
    assert response.test_candidates == 1 and response.diagnostic_groups == 1


def test_f02_class_and_parameter_are_not_confused_with_other_tests():
    source = "class TestA:\n    def test_same(self): pass\nclass TestB:\n    def test_same(self): pass\n"
    response = AnalyzeService().analyze(
        {"tests/test_case.py": source},
        log_content="tests/test_case.py::TestB::test_same[x] FAILED - connection refused",
    )
    assert [r.verdict for r in response.results] == ["no_known_risk", "risk_detected"]
    assert response.results[1].log_anomalies[0].metadata["test_name"].endswith("[x]")


def reviewed(repo, code, nodeid="test_case.py::test_case", label=0):
    return DatasetRecord(
        repo=repo, nodeid=nodeid, source_hash=hashlib.sha256(code.encode()).hexdigest(), environment_hash="e",
        provenance_version=3, passed=4 if label else 5, failed=1 if label else 0,
        ignored=0, runs_total=5, observation="observed_flaky" if label else "observed_pass",
        label=label, reviewed=True, review_notes="Synthetic regression, not a real benchmark",
        root_causes=("timing",) if label else (), source_code=code,
    )


def test_f04_unrelated_helpers_cannot_hide_target_clones():
    records = []
    for index, repo in enumerate(["train", "validation", "test"]):
        records.extend([
            reviewed(repo, f"def helper():\n    return {index}\ndef test_case():\n    assert True\n"),
            reviewed(repo, f"import time\ndef helper():\n    return {index}\ndef test_case():\n    time.sleep(1)\n", label=1),
        ])
    samples = prepare_samples(records)
    assert len({s.clone_hash for s in samples if s.label == 0}) == 1
    assert len({s.clone_hash for s in samples if s.label == 1}) == 1
    with pytest.raises(ValueError, match="clone leakage"):
        split_by_repo(samples, {"validation"}, {"test"})


def test_f04_equal_vectors_alone_are_not_clone_evidence():
    first, second = prepare_samples([
        reviewed("one", "def test_case():\n    assert 1 == 1\n"),
        reviewed("two", "def test_case():\n    value = []\n    assert len(value) == 0\n"),
    ])
    assert first.features == second.features
    assert first.clone_hash != second.clone_hash


def test_f04_legacy_review_does_not_override_missing_provenance():
    record = reviewed("one", "def test_case(): pass\n").model_copy(update={"provenance_version": 0})
    with pytest.raises(ValueError, match="v3 provenance"):
        prepare_samples([record])


@pytest.mark.parametrize("source,expected", [
    ("class Helper:\n    def test_not_collected(self): pass\n", []),
    ("import pytest\n@pytest.fixture\ndef test_fixture(): pass\n", []),
    ("import pytest as pt\n@pt.fixture()\nasync def test_fixture(): pass\n", []),
    ("class TestHidden:\n    __test__ = False\n    def test_no(self): pass\n", []),
    ("class TestConstructor:\n    def __init__(self): pass\n    def test_no(self): pass\n", []),
    ("class TestGood:\n    def test_ok(self): pass\n", ["TestGood::test_ok"]),
    ("def testPlain(): pass\n", ["testPlain"]),
])
def test_f07_default_static_discovery_excludes_helpers_and_fixtures(source, expected):
    response = AnalyzeService().analyze({"test_case.py": source})
    actual = [r.test_name for r in response.results if r.result_kind == "test_candidate"]
    assert actual == expected
    assert response.test_candidates == len(expected)
    assert response.collected_tests is None  # We never executed pytest collection.


def test_f08_selected_is_not_parsed_and_groups_are_not_tests():
    response = AnalyzeService().analyze({
        "test_good.py": "def test_good(): pass\n",
        "test_bad.py": "def broken(:",
    })
    assert (response.files_selected, response.files_parsed, response.files_rejected) == (2, 1, 1)
    assert response.total_files_analyzed == 1
    assert response.test_candidates == 1 and response.diagnostic_groups == 1


def test_f08_shared_fixture_has_one_risk_location_two_affected_tests_and_source():
    response = AnalyzeService().analyze({
        "conftest.py": 'import pytest\n@pytest.fixture(scope="session")\ndef state():\n    return {}\n',
        "test_case.py": "def test_one(state): pass\ndef test_two(state): pass\n",
    })
    assert response.unique_risk_locations == 1
    assert response.tests_with_risk == response.evidence_links == 2
    assert response.test_candidates == 2 and response.context_files_selected == 1
    assert response.results[0].patterns[0].code_snippet
    assert "return {}" in response.results[0].patterns[0].code_snippet


@pytest.mark.parametrize("reports,expected", [
    ({"setup": ("skipped", True), "teardown": ("passed", False)}, "xfailed"),
    ({"setup": ("passed", False), "call": ("skipped", True), "teardown": ("passed", False)}, "xfailed"),
    ({"setup": ("passed", False), "call": ("passed", True), "teardown": ("passed", False)}, "xpassed"),
    ({"setup": ("passed", False), "call": ("passed", False), "teardown": ("skipped", True)}, "xfailed"),
    ({"setup": ("passed", False), "call": ("failed", False), "teardown": ("skipped", True)}, "failed"),
    ({"setup": ("passed", False), "call": ("passed", True), "teardown": ("failed", False)}, "error"),
    ({"setup": ("passed", False), "call": ("rerun", False), "teardown": ("passed", False)}, "failed"),
    ({"setup": ("passed", False)}, "incomplete"),
])
def test_f06_terminal_phase_table(reports, expected):
    assert TrailStorage._terminal(reports) == expected
