"""Human lifecycle/review events; adoption is not an analyzer-accuracy label."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from flakydetector.models.domain import ValueModel
from flakydetector.runtime.store import EventConflict, EvidenceStore


class LifecycleEvent(ValueModel):
    event_id: str = Field(min_length=1, max_length=128)
    workspace: str = Field(min_length=1, max_length=100)
    repo: str = Field(min_length=1, max_length=256)
    finding_id: str = Field(pattern="^[a-f0-9]{64}$")
    kind: Literal[
        "opened",
        "triaged",
        "fixed",
        "reopened",
        "review_true_positive",
        "review_false_positive",
        "review_unknown",
    ]
    at: datetime
    actor: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=2000)
    independent_review: bool = False

    @field_validator("at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Aware timestamp required")
        return value


class LifecycleStore:
    def __init__(self, store: EvidenceStore) -> None:
        self.store = store
        with store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS finding_lifecycle (workspace TEXT,event_id TEXT,payload TEXT NOT NULL,PRIMARY KEY(workspace,event_id))",
            )

    def append(self, event: LifecycleEvent, *, actor: str) -> bool:
        if actor != event.actor:
            raise ValueError("Actor must match authenticated subject")
        from flakydetector.security.privacy import redact

        event = event.model_copy(update={"note": redact(event.note)})
        payload = event.model_dump_json()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM finding_lifecycle WHERE workspace=? AND event_id=?",
                (event.workspace, event.event_id),
            ).fetchone()
            if row:
                if row[0] != payload:
                    raise EventConflict("Lifecycle event ID reused")
                return False
            db.execute(
                "INSERT INTO finding_lifecycle VALUES(?,?,?)",
                (event.workspace, event.event_id, payload),
            )
            return True

    def list(self, workspace: str, repo: str) -> tuple[LifecycleEvent, ...]:
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT payload FROM finding_lifecycle WHERE workspace=?", (workspace,)
            ).fetchall()
        return tuple(
            e for r in rows if (e := LifecycleEvent.model_validate_json(r[0])).repo == repo
        )
