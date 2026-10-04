"""Comparable execution observations; these labels do not claim a causal root cause."""

from __future__ import annotations

import ast
import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from flakydetector.models.domain import ValueModel
from flakydetector.utils.provenance import source_fingerprint


class DatasetRecord(ValueModel):
    repo: str
    nodeid: str
    source_hash: str
    environment_hash: str
    provenance_version: int = 0
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    ignored: int = Field(ge=0)
    runs_total: int = Field(ge=0)
    observation: Literal["observed_flaky", "observed_pass", "observed_fail", "inconclusive"]
    label: Literal[0, 1] | None
    reviewed: bool = False
    root_causes: tuple[str, ...] = ()
    review_notes: str = ""
    context_sources: dict[str, str] = Field(default_factory=dict)
    source_code: str | None = None
    sample_tracebacks: tuple[str, ...] = ()

    @model_validator(mode="after")
    def consistent_observation(self) -> Self:
        if self.runs_total != self.passed + self.failed:
            raise ValueError("runs_total must count passed and failed terminal observations only")
        expected = (
            "observed_flaky"
            if self.passed and self.failed
            else ("observed_pass" if self.passed else "observed_fail")
        )
        if self.observation != "inconclusive":
            if not self.runs_total or self.observation != expected:
                raise ValueError("Observation is inconsistent with outcome counts")
            if self.label != int(bool(self.passed and self.failed)):
                raise ValueError("Binary label is inconsistent with the observed outcome class")
        elif self.label is not None:
            raise ValueError("Inconclusive observations must not receive a binary label")
        return self


def extract_function_source(file_path: Path, qualified_name: str) -> str | None:
    if not file_path.is_file():
        return None
    code = file_path.read_text(encoding="utf-8")
    tree = ast.parse(code)
    parts = qualified_name.split("[")[0].split("::")
    body = tree.body
    for idx, name in enumerate(parts):
        found = next(
            (
                n
                for n in body
                if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == name
            ),
            None,
        )
        if found is None:
            return None
        if idx == len(parts) - 1 and isinstance(found, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([found.lineno, *(d.lineno for d in found.decorator_list)])
            return "\n".join(code.splitlines()[start - 1 : found.end_lineno])
        body = found.body
    return None


def export_records(
    db_path: Path, source_root: Path, *, min_runs: int = 5
) -> Iterator[DatasetRecord]:
    if min_runs < 2:
        raise ValueError("At least two comparable attempts are required")
    current_hash = source_fingerprint(source_root)
    with closing(sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if schema_version not in {2, 3}:
            raise ValueError("Expected trace schema v2/v3; legacy provenance must not be invented")
        version_column = "t.provenance_version" if schema_version == 3 else "0"
        groups = conn.execute(f"""SELECT r.repo_name,t.nodeid,t.source_hash,t.environment_hash,
            {version_column} AS provenance_version,
            SUM(t.outcome='passed') AS passed, SUM(t.outcome IN ('failed','error')) AS failed,
            SUM(t.outcome NOT IN ('passed','failed','error')) AS ignored
            FROM test_trails t JOIN test_runs r ON r.id=t.run_id
            WHERE t.source_hash != '' AND t.environment_hash != ''
            GROUP BY r.repo_name,t.nodeid,t.source_hash,t.environment_hash,provenance_version
            ORDER BY r.repo_name,t.nodeid,t.source_hash,t.environment_hash""").fetchall()
        for row in groups:
            passed, failed, ignored = int(row["passed"]), int(row["failed"]), int(row["ignored"])
            total = passed + failed
            observation: Literal[
                "observed_flaky", "observed_pass", "observed_fail", "inconclusive"
            ] = "inconclusive"
            label: Literal[0, 1] | None = None
            if total >= min_runs and int(row["provenance_version"]) == 3:
                observation = (
                    "observed_flaky"
                    if passed and failed
                    else ("observed_pass" if passed else "observed_fail")
                )
                label = 1 if passed and failed else 0
            nodeid = str(row["nodeid"])
            source = None
            context_sources: dict[str, str] = {}
            parts = nodeid.split("::", 1)
            path = (source_root / parts[0]).resolve()
            if (
                len(parts) == 2
                and str(row["source_hash"]) == current_hash
                and path.is_relative_to(source_root.resolve())
                and path.is_file()
                and extract_function_source(path, parts[1]) is not None
            ):
                source = path.read_text(
                    encoding="utf-8"
                )  # Keep module imports/fixtures as context.
                for ancestor in [path.parent, *path.parent.parents]:
                    if not ancestor.is_relative_to(source_root.resolve()):
                        break
                    config = ancestor / "conftest.py"
                    if config.is_file():
                        context_sources[config.relative_to(source_root.resolve()).as_posix()] = (
                            config.read_text(encoding="utf-8")
                        )
            traces = conn.execute(
                """SELECT DISTINCT t.traceback FROM test_trails t JOIN test_runs r ON r.id=t.run_id
                WHERE r.repo_name=? AND t.nodeid=? AND t.source_hash=? AND t.environment_hash=?
                AND t.traceback IS NOT NULL AND t.traceback != '' ORDER BY t.traceback LIMIT 2""",
                (row["repo_name"], nodeid, row["source_hash"], row["environment_hash"]),
            ).fetchall()
            yield DatasetRecord(
                repo=str(row["repo_name"]),
                nodeid=nodeid,
                source_hash=str(row["source_hash"]),
                environment_hash=str(row["environment_hash"]),
                provenance_version=int(row["provenance_version"]),
                passed=passed,
                failed=failed,
                ignored=ignored,
                runs_total=total,
                observation=observation,
                label=label,
                source_code=source,
                context_sources=context_sources,
                sample_tracebacks=tuple(str(r[0])[:8000] for r in traces),
            )


def write_dataset(records: Iterator[DatasetRecord], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")
    tmp.replace(target)
