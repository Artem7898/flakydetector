"""Resolve local/conftest fixture dependencies without importing test code."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from flakydetector.models.domain import AnalysisDiagnostic, FixtureInfo, TestDefinition

BUILTINS = {
    "request",
    "tmp_path",
    "tmp_path_factory",
    "tmpdir",
    "tmpdir_factory",
    "monkeypatch",
    "capsys",
    "capsysbinary",
    "capfd",
    "capfdbinary",
    "caplog",
    "pytestconfig",
    "cache",
    "record_property",
    "record_testsuite_property",
    "record_xml_attribute",
    "recwarn",
    "doctest_namespace",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class FixtureResolution:
    fixtures: tuple[FixtureInfo, ...]
    diagnostics: tuple[AnalysisDiagnostic, ...]


def resolve_fixtures(
    test: TestDefinition, definitions: Sequence[FixtureInfo], path: str
) -> FixtureResolution:
    # Definitions are ordered outer conftest -> inner conftest -> module -> class.
    stacks: dict[str, list[FixtureInfo]] = {}
    autouse: set[str] = set()
    for f in definitions:
        if f.class_name is not None and f.class_name != test.class_name:
            continue
        stacks.setdefault(f.fixture_name, []).append(f)
        if f.has_autouse:
            autouse.add(f.fixture_name)
    resolved: dict[tuple[str, str, int], FixtureInfo] = {}
    visiting: set[tuple[str, int]] = set()
    diagnostics: list[AnalysisDiagnostic] = []

    def visit(name: str, index: int | None = None) -> None:
        definitions_ = stacks.get(name, [])
        idx = len(definitions_) - 1 if index is None else index
        if idx < 0:
            if name not in BUILTINS:
                diagnostics.append(
                    AnalysisDiagnostic(
                        code="unresolved_fixture",
                        message=f"Fixture {name!r} requires runtime collection/plugin metadata",
                        file_path=path,
                        level="warning",
                    )
                )
            return
        identity = (name, idx)
        if identity in visiting:
            diagnostics.append(
                AnalysisDiagnostic(
                    code="fixture_cycle", message=f"Fixture cycle at {name}", file_path=path
                )
            )
            return
        f = definitions_[idx]
        key = (f.file_path, f.fixture_name, f.line)
        if key in resolved:
            return
        visiting.add(identity)
        for dep in f.dependencies:
            # pytest permits an overriding fixture to request its predecessor.
            visit(dep, idx - 1 if dep == name else None)
        visiting.remove(identity)
        resolved[key] = f
        if f.scope == "dynamic":
            diagnostics.append(
                AnalysisDiagnostic(
                    code="dynamic_fixture_scope",
                    message=f"Dynamic scope of {name} is not executed by static analysis",
                    file_path=path,
                    level="warning",
                )
            )

    for name in sorted(set(test.fixtures) | autouse):
        visit(name)
    return FixtureResolution(fixtures=tuple(resolved.values()), diagnostics=tuple(diagnostics))
