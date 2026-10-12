"""Opt-in report recorder; per-session state lives in pytest's plugin manager."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

import pytest
from pluggy import Result

from flakydetector.pytest_flaky_trail.context import execution_snapshot
from flakydetector.pytest_flaky_trail.storage import TrailStorage
from flakydetector.reporting.findings import digest
from flakydetector.runtime.models import ExecutionEvent, Outcome, Provenance
from flakydetector.runtime.store import EvidenceStore
from flakydetector.security.privacy import redact
from flakydetector.utils.provenance import environment_fingerprint, source_fingerprint

SESSION_KEY: pytest.StashKey[str] = pytest.StashKey()


def _report_failure_kind(
    report: pytest.TestReport,
) -> Literal["timeout", "assertion", "exception", "unknown"]:
    """Read the recorder's namespaced public pytest report property."""
    for key, value in reversed(report.user_properties):
        if key != "flakydetector.failure_kind":
            continue
        if value == "timeout":
            return "timeout"
        if value == "assertion":
            return "assertion"
        if value == "exception":
            return "exception"
        return "unknown"
    return "unknown"


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
    events: EvidenceStore | None = None
    event_provenance: Provenance | None = None
    session_id: str = ""
    repo: str = ""
    workspace: str = "local"
    sequence: int = 0
    source_root: Path | None = None

    @pytest.hookimpl(trylast=True)
    def pytest_collection_finish(self, session: pytest.Session) -> None:
        snapshot = execution_snapshot(session.config, [item.nodeid for item in session.items])
        serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        self.environment_hash = hashlib.sha256(
            (self.environment_hash + "\x00" + serialized).encode()
        ).hexdigest()
        self.provenance_version = 3 if snapshot["comparable_under_recorded_context"] else 0
        self.storage.save_execution_context(
            self.run_id,
            self.worker_id,
            self.environment_hash,
            serialized,
        )

        def option(name: str) -> str:
            return str(session.config.getoption(name, default=""))

        revision = option("flaky_trail_revision")
        dirty = None
        try:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=session.config.rootpath,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
            revision = revision or head
            status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=session.config.rootpath,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout
            # DB/log outputs are not source changes. The source fingerprint still covers
            # all accepted source/config inputs, including untracked Python files.
            dirty = revision != head or any(
                (
                    line[3:].endswith(
                        (
                            ".py",
                            "pyproject.toml",
                            "uv.lock",
                            "poetry.lock",
                            "pytest.ini",
                            "setup.cfg",
                            "tox.ini",
                        ),
                    )
                    for line in status.splitlines()
                ),
            )
        except (OSError, subprocess.SubprocessError):
            pass
        components = {
            "python": digest(sys.version),
            "dependencies": digest(
                sorted((str(d.metadata.get("Name", "")), d.version) for d in distributions())
            ),
            "config": digest(
                {
                    k: v
                    for k, v in snapshot.items()
                    if k not in {"collection_order", "collection_count"}
                },
            ),
            "collection": digest(snapshot["collection_order"]),
            "external_state": digest(option("flaky_trail_env"))
            if option("flaky_trail_env")
            else "",
            "seed": digest(option("flaky_trail_seed_id")) if option("flaky_trail_seed_id") else "",
            "image": option("flaky_trail_image"),
        }
        self.event_provenance = Provenance(
            source_hash=self.source_hash,
            environment_hash=self.environment_hash,
            revision=revision,
            dirty=dirty,
            recorded_context_complete=bool(snapshot["comparable_under_recorded_context"]),
            components=components,
            experiment_id=option("flaky_trail_experiment"),
            treatment_axis=cast(
                Literal["none", "order", "image"], option("flaky_trail_treatment_axis")
            ),
            treatment_value=option("flaky_trail_treatment"),
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
            traceback=redact(str(report.longrepr)) if report.longrepr is not None else None,
            wasxfail=hasattr(report, "wasxfail"),
            source_hash=self.source_hash,
            environment_hash=self.environment_hash,
            provenance_version=self.provenance_version,
        )
        # Retry plugins rewrite failed -> rerun before logreport; longrepr still
        # contains the failure. A blank xfail reason is still an expected outcome.
        if self.events is not None and self.event_provenance is not None:
            self.sequence += 1
            attempt = self.attempts.get(report.nodeid, 1)
            outcome = report.outcome
            if outcome == "failed" and str(report.longrepr).startswith("[XPASS(strict)]"):
                outcome = "xpassed"
            file_hash = None
            if self.source_root is not None:
                path = (self.source_root / report.nodeid.split("::", 1)[0]).resolve()
                if (
                    path.is_relative_to(self.source_root.resolve())
                    and path.is_file()
                    and (path.stat().st_size <= 1000000)
                ):
                    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            event = ExecutionEvent(
                event_id=digest(
                    [self.session_id, self.worker_id, report.nodeid, attempt, report.when]
                ),
                workspace=self.workspace,
                repo=self.repo,
                run_id=self.session_id,
                invocation_id=digest([self.session_id, self.worker_id, report.nodeid]),
                nodeid=report.nodeid,
                worker=self.worker_id,
                attempt=attempt,
                phase=report.when,
                sequence=self.sequence,
                outcome=cast(Outcome, outcome),
                started_at=datetime.fromtimestamp(report.start, UTC),
                ended_at=datetime.fromtimestamp(max(report.start, report.stop), UTC),
                duration=max(0, report.duration),
                expected=hasattr(report, "wasxfail"),
                failure_kind=_report_failure_kind(report),
                traceback=redact(str(report.longrepr))[:8000]
                if report.longrepr is not None
                else None,
                provenance=self.event_provenance,
                source_file_hash=file_hash,
            )
            self.events.ingest([event], workspace=self.workspace)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_makereport(
        self, item: pytest.Item, call: pytest.CallInfo[Any]
    ) -> Generator[None, Result[pytest.TestReport], None]:
        outcome = yield
        report = outcome.get_result()
        if call.excinfo:
            name = call.excinfo.type.__name__
            report.user_properties[:] = [
                (key, value)
                for key, value in report.user_properties
                if key != "flakydetector.failure_kind"
            ]
            report.user_properties.append(
                (
                    "flakydetector.failure_kind",
                    "timeout"
                    if name == "TimeoutError"
                    else "assertion"
                    if name == "AssertionError"
                    else "exception",
                )
            )

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if exitstatus not in {2, 3, 4, 5} or self.events is None:
            return
        now = datetime.now(UTC)
        provenance = self.event_provenance or Provenance(
            source_hash=self.source_hash, environment_hash=self.environment_hash
        )
        event = ExecutionEvent(
            event_id=digest([self.session_id, self.worker_id, "session", exitstatus]),
            workspace=self.workspace,
            repo=self.repo,
            run_id=self.session_id,
            invocation_id=digest([self.session_id, "session"]),
            nodeid="<session>",
            worker=self.worker_id,
            attempt=1,
            phase="session",
            sequence=self.sequence + 1,
            outcome="error",
            started_at=now,
            ended_at=now,
            duration=0,
            failure_kind="collection" if exitstatus in {2, 5} else "interrupted",
            provenance=provenance,
        )
        self.events.ingest([event], workspace=self.workspace)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("flaky-trail")
    group.addoption(
        "--flaky-trail",
        action="store_true",
        help="Record setup/call/teardown execution evidence",
    )
    group.addoption("--flaky-trail-db", default="flaky_trails.db", help="SQLite ledger path")
    group.addoption(
        "--flaky-trail-repo",
        default=None,
        help="Stable repository identity, e.g. owner/repo",
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
    group.addoption("--flaky-trail-workspace", default="local")
    group.addoption(
        "--flaky-trail-image",
        default="",
        help="Non-secret runner/container image identity",
    )
    group.addoption(
        "--flaky-trail-seed-id", default="", help="Non-secret identity of controlled seeds"
    )
    group.addoption("--flaky-trail-experiment", default="")
    group.addoption(
        "--flaky-trail-treatment-axis", choices=["none", "order", "image"], default="none"
    )
    group.addoption("--flaky-trail-treatment", default="")


def pytest_configure(config: pytest.Config) -> None:
    if not config.getoption("flaky_trail"):
        return
    worker = cast(dict[str, object] | None, getattr(config, "workerinput", None))
    session_id = (
        str(worker["flaky_session_id"])
        if worker and "flaky_session_id" in worker
        else os.environ.get("FLAKY_RUN_ID") or str(uuid4())
    )
    config.stash[SESSION_KEY] = session_id
    if not worker and config.getoption("numprocesses", default=0):
        # Workers record reports; do not duplicate forwarded reports in the master.
        return
    root = Path(config.rootpath)
    storage = TrailStorage(str(config.getoption("flaky_trail_db")))
    extra_env = str(config.getoption("flaky_trail_env"))
    env_hash = hashlib.sha256((environment_fingerprint() + "\x00" + extra_env).encode()).hexdigest()
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
            events=EvidenceStore(Path(str(config.getoption("flaky_trail_db")))),
            session_id=session_id,
            repo=repo,
            source_root=root,
            workspace=str(config.getoption("flaky_trail_workspace")),
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
