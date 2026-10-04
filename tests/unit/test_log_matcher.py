"""Explicit log-matcher inputs cannot inherit another analysis loop iteration."""

from __future__ import annotations

import pytest

from flakydetector.application import AnalyzeService, _belongs_to_test
from flakydetector.models.domain import TestDefinition as Definition


@pytest.mark.parametrize(
    "nodeid,expected",
    [
        ("tests/test_a.py::TestA::test_same", True),
        ("tests/test_a.py::TestA::test_same[param]", True),
        (r"tests\test_a.py::TestA::test_same", True),
        ("other/test_a.py::TestA::test_same", False),
        ("tests/test_a.py::TestB::test_same", False),
        ("tests/test_a.py::TestA::test_other", False),
        ("test_same", False),
        (None, False),
    ],
)
def test_full_path_class_name_and_parameters_are_matched(nodeid, expected):
    definition = Definition(name="test_same", class_name="TestA", line=1)
    assert _belongs_to_test(nodeid, file_path="tests/test_a.py", test=definition) is expected


def test_module_placeholder_cannot_receive_test_evidence():
    assert not _belongs_to_test(
        "test_a.py::<module>", file_path="test_a.py", test=Definition(name="<module>", line=1)
    )


def test_matching_in_multiple_files_does_not_use_the_last_loop_values():
    response = AnalyzeService().analyze(
        {
            "tests/test_a.py": "def test_same(): pass\ndef test_other(): pass\n",
            "tests/test_b.py": "def test_same(): pass\ndef test_other(): pass\n",
        },
        log_content="tests/test_a.py::test_same FAILED - connection refused",
    )
    observed = {
        (r.file_path, r.test_name): r.verdict
        for r in response.results
        if r.result_kind == "test_candidate"
    }
    assert observed == {
        ("tests/test_a.py", "test_same"): "risk_detected",
        ("tests/test_a.py", "test_other"): "no_known_risk",
        ("tests/test_b.py", "test_same"): "no_known_risk",
        ("tests/test_b.py", "test_other"): "no_known_risk",
    }
