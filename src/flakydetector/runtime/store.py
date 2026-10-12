"""Workspace-scoped append-only events with idempotency, retention and bounded reads."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from flakydetector.runtime.models import ExecutionEvent
from flakydetector.security.privacy import redact


class EventConflict(ValueError):
    pass


class EvidenceStore:
    def __init__(self, path: Path, *, retain_tracebacks: bool = True) -> None:
        self.path = path
        self.retain_tracebacks = retain_tracebacks
        path.parent.mkdir(parents=True, exist_ok=True)
        created = not path.exists()
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS fd_evidence_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)",
            )
            row = db.execute(
                "SELECT version FROM fd_evidence_schema WHERE component='events'"
            ).fetchone()
            if row and row[0] != 1:
                raise ValueError("Unsupported event store schema")
            db.execute("INSERT OR IGNORE INTO fd_evidence_schema VALUES('events',1)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_events (\n                id INTEGER PRIMARY KEY AUTOINCREMENT, workspace TEXT NOT NULL, repo TEXT NOT NULL,\n                event_id TEXT NOT NULL, ended_at TEXT NOT NULL, payload TEXT NOT NULL,\n                UNIQUE(workspace,event_id))",
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS event_payload_hashes (workspace TEXT NOT NULL,event_id TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(workspace,event_id))",
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS event_scope_time ON execution_events(workspace,repo,ended_at,id)",
            )
        if created:
            os.chmod(path, 384)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, events: Sequence[ExecutionEvent], *, workspace: str) -> tuple[int, int]:
        if len(events) > 2000:
            raise ValueError("Maximum 2000 events per upload")
        added = duplicates = 0
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for event in events:
                if event.workspace != workspace:
                    raise ValueError("Event workspace does not match authorized scope")
                sanitized = event.model_copy(
                    update={
                        "traceback": redact(event.traceback)
                        if event.traceback and self.retain_tracebacks
                        else None,
                    },
                )
                value = json.dumps(
                    sanitized.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                )
                original_hash = hashlib.sha256(
                    json.dumps(
                        event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                    ).encode(),
                ).hexdigest()
                original = db.execute(
                    "SELECT digest FROM event_payload_hashes WHERE workspace=? AND event_id=?",
                    (workspace, event.event_id),
                ).fetchone()
                existing = db.execute(
                    "SELECT payload FROM execution_events WHERE workspace=? AND event_id=?",
                    (workspace, event.event_id),
                ).fetchone()
                if existing:
                    if existing[0] != value or (original and original[0] != original_hash):
                        raise EventConflict("Event ID was reused with different content")
                    duplicates += 1
                else:
                    db.execute(
                        "INSERT INTO execution_events(workspace,repo,event_id,ended_at,payload) VALUES(?,?,?,?,?)",
                        (
                            workspace,
                            event.repo,
                            event.event_id,
                            event.ended_at.astimezone(UTC).isoformat(),
                            value,
                        ),
                    )
                    db.execute(
                        "INSERT INTO event_payload_hashes VALUES(?,?,?)",
                        (workspace, event.event_id, original_hash),
                    )
                    added += 1
        return (added, duplicates)

    def page(
        self, *, workspace: str, repo: str, cursor: int = 0, limit: int = 1000
    ) -> tuple[list[ExecutionEvent], int | None]:
        if cursor < 0 or not 1 <= limit <= 10000:
            raise ValueError("Invalid event page")
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,payload FROM execution_events WHERE workspace=? AND repo=? AND id>? ORDER BY id LIMIT ?",
                (workspace, repo, cursor, limit + 1),
            ).fetchall()
        return (
            [ExecutionEvent.model_validate_json(r[1]) for r in rows[:limit]],
            rows[limit - 1][0] if len(rows) > limit else None,
        )

    def prune(self, *, workspace: str, older_than: datetime, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        if older_than.tzinfo is None or older_than > now:
            raise ValueError("Invalid retention boundary")
        with self.connection() as db:
            cursor = db.execute(
                "DELETE FROM execution_events WHERE workspace=? AND ended_at<?",
                (workspace, older_than.astimezone(UTC).isoformat()),
            )
            count = cursor.rowcount
            db.execute(
                "DELETE FROM event_payload_hashes WHERE workspace=? AND event_id NOT IN (SELECT event_id FROM execution_events WHERE workspace=?)",
                (workspace, workspace),
            )
            return count
