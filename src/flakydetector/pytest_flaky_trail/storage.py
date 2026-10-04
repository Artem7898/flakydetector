"""Versioned SQLite ledger. Connections and transactions have explicit lifetimes."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class TrailStorage:
    def __init__(self, db_path: str | Path = "flaky_trails.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > 3:
                raise ValueError("Trace database uses a newer schema")
            conn.execute("""CREATE TABLE IF NOT EXISTS test_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL, repo_name TEXT, environment TEXT)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS test_trails (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                nodeid TEXT NOT NULL, outcome TEXT NOT NULL, duration REAL NOT NULL,
                traceback TEXT, FOREIGN KEY(run_id) REFERENCES test_runs(id))""")
            # Preserve legacy rows, but mark missing provenance as empty, never comparable.
            additions = {
                "test_runs": {
                    "session_id": "TEXT",
                    "revision": "TEXT NOT NULL DEFAULT ''",
                    "source_root": "TEXT NOT NULL DEFAULT ''",
                },
                "test_trails": {
                    "worker_id": "TEXT NOT NULL DEFAULT 'legacy'",
                    "attempt": "INTEGER NOT NULL DEFAULT 1",
                    "source_hash": "TEXT NOT NULL DEFAULT ''",
                    "environment_hash": "TEXT NOT NULL DEFAULT ''",
                    "provenance_version": "INTEGER NOT NULL DEFAULT 0",
                },
            }
            for table, columns in additions.items():
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                for name, definition in columns.items():
                    if name not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS runs_session ON test_runs(session_id)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS trails_identity ON test_trails(nodeid, source_hash, environment_hash)"
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS phase_reports (
                run_id INTEGER NOT NULL, nodeid TEXT NOT NULL, worker_id TEXT NOT NULL,
                attempt INTEGER NOT NULL, phase TEXT NOT NULL,
                outcome TEXT NOT NULL, duration REAL NOT NULL, traceback TEXT, wasxfail INTEGER NOT NULL,
                source_hash TEXT NOT NULL, environment_hash TEXT NOT NULL,
                PRIMARY KEY(run_id, nodeid, worker_id, attempt, phase),
                FOREIGN KEY(run_id) REFERENCES test_runs(id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS execution_contexts (
                run_id INTEGER NOT NULL, worker_id TEXT NOT NULL,
                environment_hash TEXT NOT NULL, snapshot_json TEXT NOT NULL,
                PRIMARY KEY(run_id, worker_id), FOREIGN KEY(run_id) REFERENCES test_runs(id))""")
            conn.execute("PRAGMA user_version=3")

    def start_run(
        self,
        repo_name: str = "unknown",
        env: str = "local",
        *,
        session_id: str | None = None,
        revision: str = "",
        source_root: str = "",
    ) -> int:
        session = session_id or str(uuid4())
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO test_runs(run_timestamp,repo_name,environment,session_id,revision,source_root) VALUES(?,?,?,?,?,?) ON CONFLICT(session_id) DO NOTHING",
                (datetime.now(UTC).isoformat(), repo_name, env, session, revision, source_root),
            )
            row = conn.execute("SELECT id FROM test_runs WHERE session_id=?", (session,)).fetchone()
            if row is None:
                raise RuntimeError("Could not persist trace session")
            return int(row[0])

    def save_execution_context(
        self, run_id: int, worker_id: str, environment_hash: str, snapshot_json: str
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO execution_contexts VALUES(?,?,?,?)",
                (run_id, worker_id, environment_hash, snapshot_json),
            )

    def save_trail(
        self,
        run_id: int,
        nodeid: str,
        outcome: str,
        duration: float,
        traceback: str | None,
        *,
        worker_id: str = "legacy",
        attempt: int = 1,
        source_hash: str = "",
        environment_hash: str = "",
        provenance_version: int = 0,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO test_trails(run_id,nodeid,outcome,duration,traceback,worker_id,attempt,source_hash,environment_hash,provenance_version) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    nodeid,
                    outcome,
                    duration,
                    traceback,
                    worker_id,
                    attempt,
                    source_hash,
                    environment_hash,
                    provenance_version,
                ),
            )

    def record_phase(
        self,
        *,
        run_id: int,
        nodeid: str,
        worker_id: str,
        attempt: int,
        phase: str,
        outcome: str,
        duration: float,
        traceback: str | None,
        wasxfail: bool,
        source_hash: str,
        environment_hash: str,
        provenance_version: int = 0,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO phase_reports VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    nodeid,
                    worker_id,
                    attempt,
                    phase,
                    outcome,
                    duration,
                    traceback,
                    int(wasxfail),
                    source_hash,
                    environment_hash,
                ),
            )
            rows = conn.execute(
                "SELECT phase,outcome,duration,traceback,wasxfail FROM phase_reports WHERE run_id=? AND nodeid=? AND worker_id=? AND attempt=?",
                (run_id, nodeid, worker_id, attempt),
            ).fetchall()
            reports = {
                str(row[0]): (
                    "xpassed" if str(row[1]) == "failed" and str(row[3]).startswith("[XPASS(strict)]")
                    else str(row[1]),
                    bool(row[4]),
                ) for row in rows
            }
            terminal = self._terminal(reports) if phase == "teardown" else "incomplete"
            conn.execute(
                "DELETE FROM test_trails WHERE run_id=? AND nodeid=? AND worker_id=? AND attempt=?",
                (run_id, nodeid, worker_id, attempt),
            )
            conn.execute(
                "INSERT INTO test_trails(run_id,nodeid,outcome,duration,traceback,worker_id,attempt,source_hash,environment_hash,provenance_version) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    nodeid,
                    terminal,
                    sum(float(row[2]) for row in rows),
                    "\n".join(str(row[3]) for row in rows if row[3]),
                    worker_id,
                    attempt,
                    source_hash,
                    environment_hash,
                    provenance_version,
                ),
            )

    @staticmethod
    def _terminal(reports: dict[str, tuple[str, bool]]) -> str:
        # Missing setup/teardown means the attempt was never fully observed.
        if "setup" not in reports or "teardown" not in reports:
            return "incomplete"
        if any(
            outcome in {"failed", "rerun"} and not xfail
            for phase, (outcome, xfail) in reports.items() if phase != "call"
        ):
            return "error"
        call = reports.get("call")
        if call and call[0] in {"failed", "rerun"} and not call[1]:
            return "failed"
        if any(xfail and outcome != "passed" for outcome, xfail in reports.values()):
            return "xfailed"
        if any(outcome == "skipped" for outcome, _ in reports.values()):
            return "skipped"
        if call is None:
            return "incomplete"
        if any(outcome == "xpassed" for outcome, _ in reports.values()):
            return "xpassed"
        if any(outcome not in {"passed", "failed", "rerun", "skipped"} for outcome, _ in reports.values()):
            return "unknown"
        if any(xfail for _, xfail in reports.values()):
            return "xpassed"
        return "passed" if all(outcome == "passed" for outcome, _ in reports.values()) else "incomplete"
