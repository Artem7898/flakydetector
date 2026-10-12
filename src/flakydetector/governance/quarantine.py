"""Time-limited quarantine changes gate decisions, never pytest outcomes or evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from flakydetector.models.domain import ValueModel
from flakydetector.runtime.store import EvidenceStore


class QuarantineEntry(ValueModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    workspace: str = Field(pattern="^[A-Za-z0-9_-]{1,100}$")
    repo: str = Field(min_length=1, max_length=256)
    nodeid: str = Field(min_length=1, max_length=2000)
    source_hash: str = Field(pattern="^[a-f0-9]{64}$")
    owner: str = Field(min_length=1, max_length=200)
    issue: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=10, max_length=2000)
    approved_by: str = Field(min_length=1, max_length=200)
    created_at: datetime
    original_created_at: datetime | None = None
    expires_at: datetime
    revoked_at: datetime | None = None
    version: int = Field(default=1, ge=1)

    @field_validator("owner", "issue", "reason")
    @classmethod
    def safe_text(cls, value: str) -> str:
        from flakydetector.security.privacy import redact

        if not value.strip():
            raise ValueError("Nonblank ownership/review text required")
        return redact(value.strip())

    @model_validator(mode="after")
    def valid_dates(self) -> QuarantineEntry:
        if any(
            (
                d.tzinfo is None
                for d in (self.created_at, self.expires_at)
                + tuple((x for x in (self.original_created_at, self.revoked_at) if x is not None))
            ),
        ):
            raise ValueError("Aware timestamps required")
        if not self.created_at < self.expires_at <= self.created_at + timedelta(days=30):
            raise ValueError("TTL must be positive and at most 30 days")
        if "*" in self.nodeid or "?" in self.nodeid:
            raise ValueError("Quarantine selectors must be exact node IDs")
        return self

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and self.created_at <= now < self.expires_at


class QuarantineStore:
    def __init__(self, store: EvidenceStore) -> None:
        self.store = store
        with store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS quarantines (workspace TEXT NOT NULL,id TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(workspace,id))",
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS quarantine_audit (id INTEGER PRIMARY KEY,workspace TEXT NOT NULL,entry_id TEXT NOT NULL,version INTEGER NOT NULL,actor TEXT NOT NULL,at TEXT NOT NULL,payload TEXT NOT NULL)",
            )

    def save(self, entry: QuarantineEntry, *, actor: str, expected_version: int = 0) -> None:
        if entry.approved_by != actor:
            raise ValueError("Approver must be the authenticated actor")
        from flakydetector.security.privacy import redact

        entry = entry.model_copy(
            update={"reason": redact(entry.reason), "issue": redact(entry.issue)}
        )
        payload = entry.model_dump_json()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT version FROM quarantines WHERE workspace=? AND id=?",
                (entry.workspace, entry.id),
            ).fetchone()
            if (old[0] if old else 0) != expected_version or entry.version != expected_version + 1:
                raise ValueError("Quarantine version conflict")
            db.execute(
                "INSERT INTO quarantines VALUES(?,?,?,?) ON CONFLICT(workspace,id) DO UPDATE SET version=excluded.version,payload=excluded.payload",
                (entry.workspace, entry.id, entry.version, payload),
            )
            db.execute(
                "INSERT INTO quarantine_audit(workspace,entry_id,version,actor,at,payload) VALUES(?,?,?,?,?,?)",
                (
                    entry.workspace,
                    entry.id,
                    entry.version,
                    actor,
                    datetime.now(UTC).isoformat(),
                    payload,
                ),
            )

    def list(self, workspace: str, repo: str) -> tuple[QuarantineEntry, ...]:
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT payload FROM quarantines WHERE workspace=?", (workspace,)
            ).fetchall()
        return tuple(
            e for r in rows if (e := QuarantineEntry.model_validate_json(r[0])).repo == repo
        )

    def renew(
        self,
        *,
        workspace: str,
        id: str,
        expected_version: int,
        actor: str,
        expires_at: datetime,
        reason: str,
        now: datetime | None = None,
    ) -> QuarantineEntry:
        now = now or datetime.now(UTC)
        with self.store.connection() as db:
            row = db.execute(
                "SELECT payload FROM quarantines WHERE workspace=? AND id=?", (workspace, id)
            ).fetchone()
        if not row:
            raise ValueError("Quarantine not found")
        old = QuarantineEntry.model_validate_json(row[0])
        # Record the original creation time in the immutable audit. New approval starts a new TTL.
        entry = QuarantineEntry.model_validate(
            {
                **old.model_dump(),
                "created_at": now,
                "original_created_at": old.original_created_at or old.created_at,
                "expires_at": expires_at,
                "reason": reason,
                "approved_by": actor,
                "version": expected_version + 1,
                "revoked_at": None,
            },
        )
        self.save(entry, actor=actor, expected_version=expected_version)
        return entry

    def revoke(
        self,
        *,
        workspace: str,
        id: str,
        expected_version: int,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> QuarantineEntry:
        with self.store.connection() as db:
            row = db.execute(
                "SELECT payload FROM quarantines WHERE workspace=? AND id=?", (workspace, id)
            ).fetchone()
        if row is None:
            raise ValueError("Quarantine not found")
        old = QuarantineEntry.model_validate_json(row[0])
        updated = QuarantineEntry.model_validate(
            {
                **old.model_dump(),
                "revoked_at": now or datetime.now(UTC),
                "reason": reason,
                "approved_by": actor,
                "version": expected_version + 1,
            },
        )
        self.save(updated, actor=actor, expected_version=expected_version)
        return updated


def applies(
    entries: tuple[QuarantineEntry, ...],
    *,
    workspace: str,
    repo: str,
    nodeid: str,
    source_hash: str,
    now: datetime,
) -> bool:
    return any(
        (
            e.workspace == workspace
            and e.repo == repo
            and (e.nodeid == nodeid)
            and (e.source_hash == source_hash)
            and e.active(now)
            for e in entries
        ),
    )
