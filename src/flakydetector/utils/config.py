"""Explicit security profiles. No environment side effects and no implicit public mode."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    redactors: tuple[Callable[[str], str], ...] = ()
    max_file_bytes: int = 1000000
    max_archive_bytes: int = 10000000
    max_unpacked_bytes: int = 20000000
    max_files: int = 500
    max_entries: int = 1000
    max_path_depth: int = 24
    max_path_length: int = 512
    max_compression_ratio: float = 100.0
    max_ast_nodes: int = 50000
    timeout_seconds: float = 30.0
    worker_memory_mb: int = 1024
    worker_cpu_seconds: int = 20
    worker_output_bytes: int = 32000000
    model_path: Path | None = None
    rag_path: Path | None = None
    api_token: str | None = None
    credentials_file: Path | None = None
    profile: Literal["local", "shared"] = "local"
    allow_remote: bool = False
    source_mode: Literal["disabled", "redacted"] = "disabled"
    source_ttl_seconds: int = 300
    evidence_db: Path | None = None
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")

    def __post_init__(self) -> None:
        if (
            min(
                self.max_file_bytes,
                self.max_archive_bytes,
                self.max_unpacked_bytes,
                self.max_files,
                self.max_ast_nodes,
                self.max_entries,
                self.max_path_depth,
                self.max_path_length,
                self.worker_memory_mb,
                self.worker_cpu_seconds,
                self.worker_output_bytes,
                self.source_ttl_seconds,
            )
            <= 0
        ):
            raise ValueError("Resource limits must be positive")
        if self.timeout_seconds <= 0 or self.max_compression_ratio < 1:
            raise ValueError("Invalid timeout or compression limit")
        if self.profile not in {"local", "shared"} or self.source_mode not in {
            "disabled",
            "redacted",
        }:
            raise ValueError("Invalid security profile/source policy")
        if self.profile == "shared" and (
            not self.allow_remote or not (self.credentials_file or self.api_token)
        ):
            raise ValueError("Shared mode requires explicit remote opt-in and authentication")
        if self.profile == "shared" and self.api_token and (len(self.api_token) < 32):
            raise ValueError("Shared bearer token must contain at least 32 characters")

    @classmethod
    def from_env(cls) -> Settings:

        def path(name: str) -> Path | None:
            value = os.getenv(name)
            return Path(value) if value else None

        return cls(
            model_path=path("FLAKY_MODEL_PATH"),
            rag_path=path("FLAKY_RAG_PATH"),
            api_token=os.getenv("FLAKY_API_TOKEN") or None,
            credentials_file=path("FLAKY_CREDENTIALS_FILE"),
            profile=cast(Literal["local", "shared"], os.getenv("FLAKY_PROFILE", "local")),
            allow_remote=os.getenv("FLAKY_ALLOW_REMOTE") == "1",
            source_mode=cast(
                Literal["disabled", "redacted"], os.getenv("FLAKY_SOURCE_MODE", "disabled")
            ),
            evidence_db=path("FLAKY_EVIDENCE_DB"),
            timeout_seconds=float(os.getenv("FLAKY_TIMEOUT_SECONDS", "30")),
            worker_cpu_seconds=int(os.getenv("FLAKY_WORKER_CPU_SECONDS", "20")),
            worker_memory_mb=int(os.getenv("FLAKY_WORKER_MEMORY_MB", "1024")),
            source_ttl_seconds=int(os.getenv("FLAKY_SOURCE_TTL_SECONDS", "300")),
        )
