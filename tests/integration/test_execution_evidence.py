"""Real pytest subprocesses protect the evidence path from fixture-phase regressions."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from flakydetector.dataset.records import export_records, extract_function_source
from flakydetector.pytest_flaky_trail.storage import TrailStorage
from flakydetector.utils.provenance import source_fingerprint

SUITE = """import pytest
@pytest.fixture
def broken_setup():
    raise RuntimeError("setup failed")
@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown failed")
def test_setup(broken_setup): pass
def test_teardown(broken_teardown): pass
def test_call(): assert False
def test_ok(): pass
@pytest.mark.skip(reason="intentional")
def test_skip(): pass
@pytest.mark.xfail(reason="intentional")
def test_xfail(): assert False
@pytest.mark.xfail(reason="intentional")
def test_xpass(): pass
"""


def run_pytest(root, *extra):
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTEST_ADDOPTS"}}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "flakydetector.pytest_flaky_trail.plugin",
            "--flaky-trail",
            "--flaky-trail-db",
            str(root / "trails.db"),
            "--flaky-trail-repo",
            "example/repo",
            "-q",
            *extra,
        ],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=40,
    )
    assert result.returncode in {0, 1}, result.stdout + result.stderr
    return result


@pytest.mark.parametrize("workers", [0, 2])
def test_real_phases_serial_and_xdist(tmp_path, workers):
    (tmp_path / "test_suite.py").write_text(SUITE)
    extra = ["-p", "xdist.plugin", "-n", str(workers)] if workers else []
    run_pytest(tmp_path, *extra)
    with closing(sqlite3.connect(tmp_path / "trails.db")) as conn:
        rows = conn.execute(
            "SELECT nodeid,outcome,source_hash,environment_hash FROM test_trails"
        ).fetchall()
        outcomes = {row[0].split("::")[-1]: row[1] for row in rows}
        assert len(rows) == 7
        assert outcomes == {
            "test_setup": "error",
            "test_teardown": "error",
            "test_call": "failed",
            "test_ok": "passed",
            "test_skip": "skipped",
            "test_xfail": "xfailed",
            "test_xpass": "xpassed",
        }
        assert all(len(r[2]) == len(r[3]) == 64 for r in rows)
        assert conn.execute("SELECT COUNT(*) FROM test_runs").fetchone()[0] == 1
        assert (
            conn.execute('SELECT COUNT(*) FROM phase_reports WHERE phase="teardown"').fetchone()[0]
            == 7
        )


def test_new_session_does_not_reuse_run_id(tmp_path):
    (tmp_path / "test_suite.py").write_text("def test_ok(): pass\n")
    run_pytest(tmp_path)
    run_pytest(tmp_path)
    with closing(sqlite3.connect(tmp_path / "trails.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM test_runs").fetchone()[0] == 2
        rows = conn.execute("SELECT environment_hash FROM test_trails").fetchall()
        assert len(rows) == 2 and rows[0] == rows[1]


def test_seed_or_order_changes_comparison_fingerprint(tmp_path):
    (tmp_path / "test_suite.py").write_text("def test_a(): pass\ndef test_b(): pass\n")
    run_pytest(tmp_path, "test_suite.py::test_a", "test_suite.py::test_b")
    run_pytest(tmp_path, "test_suite.py::test_b", "test_suite.py::test_a")
    with closing(sqlite3.connect(tmp_path / "trails.db")) as conn:
        hashes = conn.execute("SELECT DISTINCT environment_hash FROM test_trails").fetchall()
        assert len(hashes) == 2


def test_interrupted_attempt_stays_incomplete(tmp_path):
    storage = TrailStorage(tmp_path / "trails.db")
    run = storage.start_run()
    storage.record_phase(
        run_id=run,
        nodeid="test_a.py::test_a",
        worker_id="main",
        attempt=1,
        phase="setup",
        outcome="passed",
        duration=0.1,
        traceback=None,
        wasxfail=False,
        source_hash="s",
        environment_hash="e",
    )
    with storage.connection() as conn:
        assert conn.execute("SELECT outcome FROM test_trails").fetchone()[0] == "incomplete"
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_legacy_migration_preserves_untrusted_rows(tmp_path):
    path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(
            'CREATE TABLE test_runs(id INTEGER PRIMARY KEY,run_timestamp TEXT,repo_name TEXT,environment TEXT); CREATE TABLE test_trails(id INTEGER PRIMARY KEY,run_id INTEGER,nodeid TEXT,outcome TEXT,duration REAL,traceback TEXT); INSERT INTO test_runs VALUES(1,"old","r","e"); INSERT INTO test_trails VALUES(1,1,"a.py::a","passed",0,NULL);'
        )
    storage = TrailStorage(path)
    with storage.connection() as conn:
        assert conn.execute("SELECT outcome,source_hash FROM test_trails").fetchone() == (
            "passed",
            "",
        )
    assert list(export_records(path, tmp_path, min_runs=2)) == []


def test_labels_require_comparable_runs_and_separate_always_failing(tmp_path):
    (tmp_path / "test_case.py").write_text("async def test_case(): pass\n")
    fingerprint = source_fingerprint(tmp_path)
    storage = TrailStorage(tmp_path / "trails.db")
    for repo, env, outcomes in [
        ("r1", "e", ["failed", "passed"]),
        ("r2", "e", ["failed", "failed"]),
        ("r1", "other", ["failed"]),
        ("r3", "e", ["skipped", "unknown"]),
    ]:
        for outcome in outcomes:
            run = storage.start_run(repo_name=repo)
            storage.save_trail(
                run,
                "test_case.py::test_case",
                outcome,
                0.1,
                None,
                source_hash=fingerprint,
                environment_hash=env,
                provenance_version=3,
            )
    records = list(export_records(storage.db_path, tmp_path, min_runs=2))
    lookup = {(r.repo, r.environment_hash): r for r in records}
    assert lookup["r1", "e"].observation == "observed_flaky"
    assert lookup["r2", "e"].observation == "observed_fail" and lookup["r2", "e"].label == 0
    assert lookup["r1", "other"].label is None
    assert lookup["r3", "e"].label is None and lookup["r3", "e"].ignored == 2
    assert all(not r.reviewed for r in records)
    assert all(r.source_code for r in records)


def test_async_class_param_source_extraction(tmp_path):
    path = tmp_path / "test_a.py"
    path.write_text(
        'import pytest\nclass TestCase:\n    @pytest.mark.parametrize("x", [1])\n    async def test_a(self, x):\n        assert x\n'
    )
    source = extract_function_source(path, "TestCase::test_a[1]")
    assert "@pytest.mark.parametrize" in source and "async def test_a" in source
