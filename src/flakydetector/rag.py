"""Versioned, non-destructive retrieval of advisory evidence; distances are not probabilities."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from importlib import import_module, metadata
from pathlib import Path
from typing import Literal, Protocol, cast
from uuid import uuid4

from pydantic import BaseModel, Field

from flakydetector.llm import AdvisoryRecord
from flakydetector.models.domain import ValueModel

EMBEDDING = "ONNXMiniLM_L6_V2/all-MiniLM-L6-v2"


class RagUnavailable(ValueError):
    pass


class RagManifest(ValueModel):
    schema_version: Literal["2.0.0"] = "2.0.0"
    collection: str
    metric: Literal["cosine"] = "cosine"
    embedding: Literal["ONNXMiniLM_L6_V2/all-MiniLM-L6-v2"] = EMBEDDING
    chroma_version: str
    count: int = Field(gt=0)


class Hit(ValueModel):
    identity: str
    nodeid: str
    repo: str
    explanation: str
    fix_strategy: str
    source_hash: str
    evidence_ids: tuple[str, ...]
    distance: float
    metric: Literal["cosine"] = "cosine"
    advisory: bool = True


class QueryResult(BaseModel):
    ids: list[list[str]]
    distances: list[list[float]]
    metadatas: list[list[dict[str, str | int | float | bool]]]


class Collection(Protocol):
    def add(
        self, *, ids: list[str], documents: list[str], metadatas: list[dict[str, str]]
    ) -> None: ...
    def count(self) -> int: ...
    def query(self, *, query_texts: list[str], n_results: int, include: list[str]) -> object: ...


class Client(Protocol):
    def create_collection(self, name: str, **kwargs: object) -> Collection: ...
    def get_collection(self, name: str, **kwargs: object) -> Collection: ...


def chroma_client(path: Path) -> tuple[Client, object, str]:
    try:
        factory = cast(Callable[..., Client], import_module("chromadb").PersistentClient)
        embedding_factory = cast(
            Callable[..., object],
            import_module("chromadb.utils.embedding_functions").ONNXMiniLM_L6_V2,
        )
        return factory(path=str(path)), embedding_factory(), metadata.version("chromadb")
    except (ImportError, OSError) as exc:
        raise RagUnavailable(f"RAG dependency unavailable: {type(exc).__name__}") from exc


class RagIndex:
    def __init__(
        self,
        path: Path,
        *,
        client: Client | None = None,
        embedding: object | None = None,
        version: str | None = None,
    ) -> None:
        self.path = path
        self.client, self.embedding, self.version = (
            (client, embedding, version or "test") if client else chroma_client(path)
        )

    def rebuild(self, records: Sequence[AdvisoryRecord]) -> RagManifest:
        unique = {r.identity: r for r in records if r.status == "ok" and r.analysis is not None}
        if not unique:
            raise RagUnavailable("No validated advisory records; current index was preserved")
        name = "flaky_" + uuid4().hex
        try:
            collection = self.client.create_collection(
                name, embedding_function=self.embedding, configuration={"hnsw": {"space": "cosine"}}
            )
            for record in unique.values():
                analysis = record.analysis
                if analysis is None:
                    continue
                collection.add(
                    ids=[record.identity],
                    documents=[analysis.root_cause_hypothesis + "\n" + analysis.explanation],
                    metadatas=[
                        {
                            "nodeid": record.nodeid,
                            "repo": record.repo,
                            "source_hash": record.source_hash,
                            "explanation": analysis.explanation,
                            "fix_strategy": analysis.fix_strategy,
                            "evidence_ids": json.dumps(analysis.evidence_ids),
                        }
                    ],
                )
            if collection.count() != len(unique):
                raise RagUnavailable("Incomplete new index; current index was preserved")
            manifest = RagManifest(collection=name, chroma_version=self.version, count=len(unique))
            self.path.mkdir(parents=True, exist_ok=True)
            temporary = self.path / f"active.{uuid4().hex}.tmp"
            temporary.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(self.path / "active.json")
            return manifest
        except Exception as exc:
            raise RagUnavailable(
                f"Index rebuild failed ({type(exc).__name__}); previous active index preserved"
            ) from exc

    def search(self, query: str, limit: int = 5) -> dict[str, object]:
        if not query.strip() or not 1 <= limit <= 50:
            raise ValueError("A nonempty query and limit in 1..50 are required")
        try:
            manifest = RagManifest.model_validate_json(
                (self.path / "active.json").read_text(encoding="utf-8")
            )
            if manifest.chroma_version != self.version:
                raise RagUnavailable(
                    "Index runtime version differs; rebuild explicitly before retrieval"
                )
            collection = self.client.get_collection(
                manifest.collection, embedding_function=self.embedding
            )
            if collection.count() != manifest.count:
                raise RagUnavailable("Active index is incomplete")
            raw = QueryResult.model_validate(
                collection.query(
                    query_texts=[query],
                    n_results=min(limit, manifest.count),
                    include=["metadatas", "distances"],
                )
            )
            hits = [
                Hit(
                    identity=identity,
                    nodeid=str(meta["nodeid"]),
                    repo=str(meta["repo"]),
                    source_hash=str(meta["source_hash"]),
                    explanation=str(meta["explanation"]),
                    fix_strategy=str(meta["fix_strategy"]),
                    evidence_ids=json.loads(str(meta["evidence_ids"])),
                    distance=distance,
                )
                for identity, meta, distance in zip(
                    raw.ids[0], raw.metadatas[0], raw.distances[0], strict=True
                )
            ]
            return {
                "results": [h.model_dump(mode="json") for h in hits],
                "index": manifest.model_dump(mode="json"),
            }
        except Exception as exc:
            raise RagUnavailable(f"Retrieval unavailable: {type(exc).__name__}") from exc
