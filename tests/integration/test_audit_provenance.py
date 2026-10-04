"""F03/F06/F12: real isolated pytest sessions and storage/export contracts."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from contextlib import closing

import pytest

from flakydetector.dataset.records import export_records
from flakydetector.pytest_flaky_trail.plugin import Recorder
from flakydetector.pytest_flaky_trail.storage import TrailStorage
from flakydetector.utils.provenance import source_fingerprint
from tests.integration.test_execution_evidence import run_pytest

WARNING_TEST = 'import warnings\ndef test_warning():\n    warnings.warn("audit", DeprecationWarning)\n'


@pytest.mark.parametrize("mode", ["cli", "setup.cfg", "tox.ini", "pytest.ini"])
def test_f03_different_warning_policies_never_form_observed_flaky(tmp_path, mode):
    (tmp_path / "test_case.py").write_text(WARNING_TEST)
    for policy in ["ignore", "ignore", "error", "error"]:
        extra = []
        if mode == "cli":
            extra = ["-o", f"filterwarnings={policy}"]
        else:
            section = "tool:pytest" if mode == "setup.cfg" else "pytest"
            (tmp_path / mode).write_text(f"[{section}]\nfilterwarnings = {policy}\n")
        run_pytest(tmp_path, *extra)
    with closing(sqlite3.connect(tmp_path / "trails.db")) as conn:
        groups = conn.execute(
            "SELECT environment_hash,COUNT(DISTINCT outcome),COUNT(*) FROM test_trails GROUP BY environment_hash"
        ).fetchall()
        assert len(groups) == 2 and all(row[1:] == (1, 2) for row in groups)
        contexts = conn.execute("SELECT snapshot_json FROM execution_contexts").fetchall()
        assert len(contexts) == 4
        assert all(json.loads(row[0])["collection_order"] == ["test_case.py::test_warning"] for row in contexts)
    records = list(export_records(tmp_path / "trails.db", tmp_path, min_runs=2))
    assert {record.observation for record in records} == {"observed_pass", "observed_fail"}
    assert all(record.label == 0 and record.provenance_version == 3 for record in records)


def test_f03_migrated_old_hashes_remain_inconclusive(tmp_path):
    (tmp_path / "test_case.py").write_text("def test_case(): pass\n")
    storage = TrailStorage(tmp_path / "trails.db")
    for outcome in ["passed", "failed"]:
        run = storage.start_run(repo_name="legacy")
        storage.save_trail(run, "test_case.py::test_case", outcome, 0, None,
                           source_hash=source_fingerprint(tmp_path), environment_hash="old-env")
    record, = export_records(storage.db_path, tmp_path, min_runs=2)
    assert record.observation == "inconclusive" and record.label is None
    assert record.provenance_version == 0


def test_f06_empty_xfail_reasons_and_teardown_real_pytest(tmp_path):
    (tmp_path / "test_case.py").write_text('''import pytest
@pytest.mark.xfail
def test_expected(): assert False
@pytest.mark.xfail
def test_unexpected(): pass
@pytest.mark.xfail(strict=True)
def test_unexpected_strict(): pass
@pytest.fixture
def setup_expected(): pytest.xfail()
def test_setup(setup_expected): pass
@pytest.fixture
def teardown_expected():
    yield
    pytest.xfail()
def test_teardown(teardown_expected): pass
''')
    run_pytest(tmp_path)
    with closing(sqlite3.connect(tmp_path / "trails.db")) as conn:
        values = dict(conn.execute("SELECT nodeid,outcome FROM test_trails"))
    assert values == {
        "test_case.py::test_expected": "xfailed",
        "test_case.py::test_unexpected": "xpassed",
        "test_case.py::test_unexpected_strict": "xpassed",
        "test_case.py::test_setup": "xfailed",
        "test_case.py::test_teardown": "xfailed",
    }
    assert all(r.label is None and r.ignored == 1 for r in export_records(tmp_path / "trails.db", tmp_path, min_runs=2))


def test_f12_rewritten_rerun_report_keeps_longrepr(tmp_path):
    storage = TrailStorage(tmp_path / "trails.db")
    recorder = Recorder(storage=storage, run_id=storage.start_run(), source_hash="s",
                        environment_hash="e", worker_id="main", provenance_version=3)
    for phase in ["setup", "call", "teardown"]:
        report = pytest.TestReport(
            nodeid="test_case.py::test_retry", location=("test_case.py", 1, "test_retry"),
            keywords={}, outcome="failed" if phase == "call" else "passed",
            longrepr="AssertionError: retry evidence" if phase == "call" else None,
            when=phase, duration=0.01,
        )
        if phase == "call":
            report.outcome = "rerun"  # The plugin's documented mutation before logreport.
        recorder.pytest_runtest_logreport(report)
    with storage.connection() as conn:
        outcome, trace = conn.execute("SELECT outcome,traceback FROM test_trails").fetchone()
        assert outcome == "failed" and "retry evidence" in trace
        assert conn.execute("SELECT outcome FROM phase_reports WHERE phase='call'").fetchone()[0] == "rerun"


@pytest.mark.skipif(importlib.util.find_spec("pytest_rerunfailures") is None,
                    reason="real retry integration requires pytest-rerunfailures")
def test_f12_real_retry_plugin_preserves_all_attempts_and_exported_tracebacks(tmp_path):
    (tmp_path / "test_case.py").write_text('''import pytest
COUNTER = 0
@pytest.mark.flaky(reruns=2)
def test_retry():
    global COUNTER
    COUNTER += 1
    assert COUNTER >= 3, "retained-failure"
''')
    run_pytest(tmp_path, "-p", "pytest_rerunfailures")
    with closing(sqlite3.connect(tmp_path / "trails.db")) as conn:
        rows = conn.execute("SELECT attempt,outcome,traceback FROM test_trails ORDER BY attempt").fetchall()
    assert [row[1] for row in rows] == ["failed", "failed", "passed"]
    assert all("retained-failure" in row[2] for row in rows[:2])
    record, = export_records(tmp_path / "trails.db", tmp_path, min_runs=2)
    assert record.observation == "observed_flaky" and record.sample_tracebacks
