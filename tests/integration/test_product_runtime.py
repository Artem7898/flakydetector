"""Real pytest subprocesses. Mandatory CI fails rather than skipping missing plugins."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

import pytest

from flakydetector.runtime.monitors import MonitorEngine, attempts_from_events
from flakydetector.runtime.store import EvidenceStore


def require_plugin(module):
    if importlib.util.find_spec(module) is None:
        if os.getenv("REQUIRE_RUNTIME_PLUGINS") == "1":
            pytest.fail(f"Mandatory runtime plugin missing: {module}")
        pytest.skip(f"Plugin unavailable locally: {module}; mandatory CI installs it")


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def init_repo(root, code):
    (root / "test_case.py").write_text(code)
    git(root, "init", "-q")
    git(root, "config", "user.name", "Regression Test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "add", "test_case.py")
    git(root, "commit", "-qm", "fixed synthetic execution fixture")


def execute(root, *args):
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTHONPATH", "PYTEST_ADDOPTS", "FLAKY_RUN_ID"}
    }
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
            str(root / "evidence.db"),
            "--flaky-trail-repo",
            "example/repo",
            "--flaky-trail-env",
            "controlled-services",
            "--flaky-trail-image",
            "synthetic-image",
            "--flaky-trail-seed-id",
            "controlled-seed",
            "-q",
            *args,
        ],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=50,
    )
    return result


def recorded(root):
    return EvidenceStore(root / "evidence.db").page(
        workspace="local", repo="example/repo", limit=10000
    )[0]


def test_mandatory_dependency_guard():
    if os.getenv("REQUIRE_RUNTIME_PLUGINS") == "1":
        for module in ("xdist", "pytest_rerunfailures", "pytest_asyncio"):
            assert importlib.util.find_spec(module) is not None, f"Missing required plugin {module}"


def test_actual_serial_events_keep_full_nodeid_and_source(tmp_path):
    init_repo(
        tmp_path,
        'import pytest\n@pytest.mark.parametrize("currency",["USD","UYU"])\ndef test_payment(currency):\n    assert currency\n',
    )
    result = execute(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    ev = recorded(tmp_path)
    attempts = attempts_from_events(ev)
    assert len(ev) == 6 and len(attempts) == 2
    assert {a.nodeid for a in attempts} == {
        "test_case.py::test_payment[USD]",
        "test_case.py::test_payment[UYU]",
    }
    assert all(
        (
            a.complete
            and a.outcome == "passed"
            and a.source_file_hash
            and (a.provenance.dirty is False)
            for a in attempts
        ),
    )
    assert all(a.comparison_status == "compatible" for a in attempts)
    assert all(a.provenance.revision for a in attempts)


def test_real_context_change_never_becomes_intermit_same_commit(tmp_path):
    init_repo(
        tmp_path,
        'import warnings\ndef test_warning():\n    warnings.warn("example",DeprecationWarning)\n',
    )
    assert execute(tmp_path, "-o", "filterwarnings=ignore").returncode == 0
    assert execute(tmp_path, "-o", "filterwarnings=error").returncode == 1
    ev = recorded(tmp_path)
    assert len({e.run_id for e in ev}) == 2
    observed = MonitorEngine().evaluate(ev)
    assert not any(
        o.monitor == "intermittent_same_commit" and o.status == "detected" for o in observed
    )


def test_actual_collection_failure_has_session_event_not_fabricated_test(tmp_path):
    init_repo(tmp_path, "def test_broken(:\n")
    result = execute(tmp_path)
    assert result.returncode == 2
    ev = recorded(tmp_path)
    assert any(e.phase == "session" and e.outcome == "error" for e in ev)
    assert attempts_from_events(ev) == ()


def test_actual_asyncio_task_execution(tmp_path):
    require_plugin("pytest_asyncio")
    init_repo(
        tmp_path,
        "import asyncio\nimport pytest\n@pytest.mark.asyncio\nasync def test_async():\n    task=asyncio.create_task(asyncio.sleep(0))\n    await task\n",
    )
    result = execute(tmp_path, "-p", "pytest_asyncio.plugin")
    assert result.returncode == 0, result.stdout + result.stderr
    attempts = attempts_from_events(recorded(tmp_path))
    assert len(attempts) == 1 and attempts[0].outcome == "passed"


@pytest.mark.parametrize("parallel", [False, True])
def test_actual_retry_tracebacks_and_monitor(tmp_path, parallel):
    require_plugin("pytest_rerunfailures")
    if parallel:
        require_plugin("xdist")
    init_repo(
        tmp_path,
        'import pytest\nCOUNTER=0\n@pytest.mark.flaky(reruns=2)\ndef test_retry():\n    global COUNTER\n    COUNTER+=1\n    assert COUNTER>=3,"retained failure"\n',
    )
    plugins = ["-p", "pytest_rerunfailures"] + (
        ["-p", "xdist.plugin", "-n", "2"] if parallel else []
    )
    result = execute(tmp_path, *plugins)
    assert result.returncode == 0, result.stdout + result.stderr
    ev = recorded(tmp_path)
    attempts = attempts_from_events(ev)
    assert [a.outcome for a in attempts] == ["failed", "failed", "passed"]
    assert all(
        "retained failure" in e.traceback for e in ev if e.phase == "call" and e.outcome == "rerun"
    )
    assert any(
        o.monitor == "pass_on_retry" and o.status == "detected"
        for o in MonitorEngine().evaluate(ev)
    )


@pytest.mark.parametrize("mode", ["load", "loadscope"])
def test_actual_xdist_preserves_sessions_without_duplicate_phases(tmp_path, mode):
    require_plugin("xdist")
    init_repo(
        tmp_path,
        'import pytest\n@pytest.mark.parametrize("value",range(8))\ndef test_param(value):\n    assert value>=0\n',
    )
    result = execute(tmp_path, "-p", "xdist.plugin", "-n", "2", "--dist", mode)
    assert result.returncode == 0, result.stdout + result.stderr
    ev = recorded(tmp_path)
    assert (
        len(ev) == 24 and len({e.event_id for e in ev}) == 24 and (len({e.run_id for e in ev}) == 1)
    )
    assert len(attempts_from_events(ev)) == 8


def test_actual_xdist_worker_crash_is_not_passed_or_observed_flake(tmp_path):
    require_plugin("xdist")
    init_repo(tmp_path, "import os\ndef test_crash():\n    os._exit(17)\n")
    result = execute(tmp_path, "-p", "xdist.plugin", "-n", "1", "--max-worker-restart", "0")
    assert result.returncode != 0
    ev = recorded(tmp_path)
    assert not any(a.outcome == "passed" for a in attempts_from_events(ev))
    assert not any(
        (
            o.verdict == "observed_flaky_behavior" and o.status == "detected"
            for o in MonitorEngine().evaluate(ev)
        ),
    )
