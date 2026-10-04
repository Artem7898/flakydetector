"""Opt-in report recorder; per-session state lives in pytest's plugin manager."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import pytest

from flakydetector.pytest_flaky_trail.context import execution_snapshot
from flakydetector.pytest_flaky_trail.storage import TrailStorage
from flakydetector.utils.provenance import environment_fingerprint, source_fingerprint

SESSION_KEY: pytest.StashKey[str] = pytest.StashKey()


class WorkerNode(Protocol):
    config: pytest.Config
    workerinput: dict[str, object]


@dataclass(slots=True, kw_only=True, eq=False)
class Recorder:
    storage: TrailStorage
    run_id: int
    source_hash: str
    environment_hash: str
    worker_id: str
    provenance_version: int = 0
    attempts: dict[str, int] = field(default_factory=lambda: dict[str, int]())

    @pytest.hookimpl(trylast=True)
    def pytest_collection_finish(self, session: pytest.Session) -> None:
        snapshot = execution_snapshot(session.config, [item.nodeid for item in session.items])
        serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        self.environment_hash = hashlib.sha256(
            (self.environment_hash + "\0" + serialized).encode()
        ).hexdigest()
        self.provenance_version = 3 if snapshot["comparable_under_recorded_context"] else 0
        self.storage.save_execution_context(
            self.run_id, self.worker_id, self.environment_hash, serialized
        )

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "setup":
            self.attempts[report.nodeid] = self.attempts.get(report.nodeid, 0) + 1
        self.storage.record_phase(
            run_id=self.run_id,
            nodeid=report.nodeid,
            worker_id=self.worker_id,
            attempt=self.attempts.get(report.nodeid, 1),
            phase=report.when,
            outcome=report.outcome,
            duration=report.duration,
            # Retry plugins rewrite failed -> rerun before logreport; longrepr still
            # contains the failure. A blank xfail reason is still an expected outcome.
            traceback=str(report.longrepr) if report.longrepr is not None else None,
            wasxfail=hasattr(report, "wasxfail"),
            source_hash=self.source_hash,
            environment_hash=self.environment_hash,
            provenance_version=self.provenance_version,
        )


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("flaky-trail")
    group.addoption(
        "--flaky-trail", action="store_true", help="Record setup/call/teardown execution evidence"
    )
    group.addoption("--flaky-trail-db", default="flaky_trails.db", help="SQLite ledger path")
    group.addoption(
        "--flaky-trail-repo", default=None, help="Stable repository identity, e.g. owner/repo"
    )
    group.addoption(
        "--flaky-trail-revision",
        default="",
        help="Source revision (optional; source fingerprint is always recorded)",
    )
    group.addoption(
        "--flaky-trail-env",
        default="",
        help="Additional non-secret environment/seed/order identifier",
    )


def pytest_configure(config: pytest.Config) -> None:
    if not config.getoption("flaky_trail"):
        return
    worker = cast(dict[str, object] | None, getattr(config, "workerinput", None))
    session_id = (
        str(worker["flaky_session_id"]) if worker and "flaky_session_id" in worker else str(uuid4())
    )
    config.stash[SESSION_KEY] = session_id
    if not worker and config.getoption("numprocesses", default=0):
        return  # Workers record reports; do not duplicate forwarded reports in the master.
    root = Path(config.rootpath)
    storage = TrailStorage(str(config.getoption("flaky_trail_db")))
    extra_env = str(config.getoption("flaky_trail_env"))
    env_hash = hashlib.sha256((environment_fingerprint() + "\0" + extra_env).encode()).hexdigest()
    repo = str(config.getoption("flaky_trail_repo") or root.resolve())
    run_id = storage.start_run(
        repo_name=repo,
        env=extra_env,
        session_id=session_id,
        revision=str(config.getoption("flaky_trail_revision")),
        source_root=str(root),
    )
    config.pluginmanager.register(
        Recorder(
            storage=storage,
            run_id=run_id,
            source_hash=source_fingerprint(root),
            environment_hash=env_hash,
            worker_id=str(worker.get("workerid", "worker")) if worker else "main",
        ),
        "flaky-trail-recorder",
    )


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node: WorkerNode) -> None:
    if SESSION_KEY in node.config.stash:
        node.workerinput["flaky_session_id"] = node.config.stash[SESSION_KEY]


def pytest_unconfigure(config: pytest.Config) -> None:
    recorder = config.pluginmanager.get_plugin("flaky-trail-recorder")
    if recorder is not None:
        config.pluginmanager.unregister(recorder)
