"""Scoped credentials. Only token digests are stored; callers enforce workspace grants."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter, ValidationError, field_validator

from flakydetector.models.domain import ValueModel

Capability = Literal[
    "analyze",
    "findings:read",
    "source:read",
    "export",
    "events:write",
    "events:read",
    "quarantine:write",
    "lifecycle:write",
]
SCOPES = frozenset(
    {
        "analyze",
        "findings:read",
        "source:read",
        "export",
        "events:write",
        "events:read",
        "quarantine:write",
        "lifecycle:write",
    },
)


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    workspaces: frozenset[str]
    scopes: frozenset[str]

    def permits(self, scope: str, workspace: str) -> bool:
        return scope in self.scopes and workspace in self.workspaces


@dataclass(frozen=True, slots=True)
class Credential:
    digest: str
    principal: Principal


class CredentialGrant(ValueModel):
    subject: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    workspaces: tuple[str, ...] = Field(min_length=1, max_length=100)
    scopes: tuple[Capability, ...] = Field(min_length=1, max_length=8)

    @field_validator("workspaces")
    @classmethod
    def workspace_identifiers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        if any(
            (
                not value or len(value) > 100 or any((c not in alphabet for c in value))
                for value in values
            ),
        ):
            raise ValueError("Invalid workspace identity")
        return values


def load_credentials(path: Path | None) -> tuple[Credential, ...]:
    if path is None:
        return ()
    if path.stat().st_size > 100000:
        raise ValueError("Credential file is too large")
    try:
        grants = TypeAdapter(tuple[CredentialGrant, ...]).validate_json(path.read_bytes())
    except ValidationError:
        raise ValueError("Invalid credential grants") from None
    if not grants or len({grant.sha256 for grant in grants}) != len(grants):
        raise ValueError("Credentials must be nonempty with unique digests")
    return tuple(
        (
            Credential(
                grant.sha256,
                Principal(grant.subject, frozenset(grant.workspaces), frozenset(grant.scopes)),
            )
            for grant in grants
        ),
    )


def authenticate(header: str, credentials: tuple[Credential, ...]) -> Principal | None:
    if not header.startswith("Bearer ") or len(header) > 4096:
        return None
    digest = hashlib.sha256(header[7:].encode()).hexdigest()
    principal: Principal | None = None
    for credential in credentials:
        if hmac.compare_digest(digest, credential.digest):
            principal = credential.principal
    return principal


def is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
