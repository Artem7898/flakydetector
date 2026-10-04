"""Explicit immutable configuration; reading settings never writes to disk."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    max_file_bytes: int = 1_000_000
    max_archive_bytes: int = 10_000_000
    max_unpacked_bytes: int = 20_000_000
    max_files: int = 500
    max_compression_ratio: float = 100.0
    max_ast_nodes: int = 50_000
    timeout_seconds: float = 30.0
    model_path: Path | None = None
    rag_path: Path | None = None
    api_token: str | None = None
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)

    def __post_init__(self) -> None:
        if (
            min(
                self.max_file_bytes,
                self.max_archive_bytes,
                self.max_unpacked_bytes,
                self.max_files,
                self.max_ast_nodes,
            )
            <= 0
        ):
            raise ValueError("Resource limits must be positive")
        if self.timeout_seconds <= 0 or self.max_compression_ratio < 1:
            raise ValueError("Invalid timeout or compression limit")

    @classmethod
    def from_env(cls) -> Settings:
        model = os.getenv("FLAKY_MODEL_PATH")
        rag = os.getenv("FLAKY_RAG_PATH")
        return cls(
            model_path=Path(model) if model else None,
            rag_path=Path(rag) if rag else None,
            api_token=os.getenv("FLAKY_API_TOKEN") or None,
        )
