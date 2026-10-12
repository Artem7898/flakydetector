"""Canonical findings and line-shift-stable identities, independent of transport."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping

from flakydetector.analyzer.syntax import character_column, imports, resolve
from flakydetector.models.domain import AnalysisResponse, ASTPattern, StaticFinding
from flakydetector.reporting.catalog import FINGERPRINT_VERSION, RULES
from flakydetector.security.privacy import safe_path


def digest(parts: object) -> str:
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()


class Canonical(ast.NodeTransformer):
    def __init__(self, aliases: dict[str, str]) -> None:
        self.aliases = aliases

    def visit_Call(self, node: ast.Call) -> ast.AST:
        target = resolve(node.func, self.aliases)
        visited = self.generic_visit(node)
        if isinstance(visited, ast.Call) and target:
            visited.func = ast.Name(id=target, ctx=ast.Load())
        return visited


def signature(pattern: ASTPattern, tree: ast.Module | None, source: str) -> str:
    if tree is None:
        return pattern.pattern_type
    loc = pattern.location
    lines = source.splitlines()
    candidates = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.expr, ast.stmt))
        and n.lineno == loc.line_start
        and (
            loc.column_start is None
            or character_column(lines, n.lineno, n.col_offset) == loc.column_start
        )
    ]
    # Prefer the whole call/operator at the reported coordinate, not its Name child.
    preferred = [
        n for n in candidates if isinstance(n, (ast.Call, ast.Compare, ast.Assign, ast.AugAssign))
    ]
    node = max(preferred or candidates, key=lambda n: len(ast.dump(n))) if candidates else None
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return digest([pattern.pattern_type, node.name, ast.dump(node.args)])
    if node is None:
        return pattern.pattern_type
    return ast.dump(Canonical(imports(tree)).visit(copy.deepcopy(node)), include_attributes=False)


def build_findings(
    response: AnalysisResponse, sources: Mapping[str, str]
) -> tuple[StaticFinding, ...]:
    trees: dict[str, ast.Module | None] = {}
    for path, code in sources.items():
        try:
            trees[path] = ast.parse(code)
        except (SyntaxError, ValueError, RecursionError):
            trees[path] = None
    grouped: dict[tuple[str, int, int, str, str], list[tuple[ASTPattern, str]]] = defaultdict(list)
    for result in response.results:
        for p in result.patterns:
            if p.confidence < 0.5:
                continue
            key = (
                p.location.file_path,
                p.location.line_start,
                p.location.column_start or 0,
                p.pattern_type,
                p.location.function_name or "",
            )
            nodeid = (
                f"{result.file_path}::{result.test_name}"
                if result.result_kind == "test_candidate"
                else ""
            )
            grouped[key].append((p, nodeid))
    occurrences: dict[str, int] = defaultdict(int)
    findings: list[StaticFinding] = []
    for _key, associations in sorted(grouped.items()):
        pattern = associations[0][0]
        rule = RULES.get(pattern.pattern_type)
        if rule is None:
            raise ValueError(f"No versioned rule for {pattern.pattern_type}")
        path = safe_path(pattern.location.file_path)
        base = digest(
            [
                FINGERPRINT_VERSION,
                path,
                pattern.location.class_name,
                pattern.location.function_name,
                rule.id,
                signature(pattern, trees.get(path), sources.get(path, "")),
            ],
        )
        occurrence = occurrences[base]
        occurrences[base] += 1
        facts = [rule.title]
        call = pattern.metadata.get("network_call")
        if isinstance(call, str) and all(c.isalnum() or c in "._" for c in call):
            facts.append(f"Resolved call: {call}")
        timeout = pattern.metadata.get("timeout_seconds")
        if isinstance(timeout, (float, int)) and (not isinstance(timeout, bool)):
            facts.append(f"Literal timeout: {timeout:g} seconds")
        findings.append(
            StaticFinding(
                finding_id=digest([base, occurrence]),
                rule_id=rule.id,
                rule_version=rule.version,
                title=rule.title,
                severity=pattern.severity,
                confidence=pattern.confidence,
                location=pattern.location,
                test_nodeids=tuple(sorted({n for _, n in associations if n})),
                facts=tuple(facts),
                limitations=(
                    rule.limitation,
                    "Dynamic bindings or unsupported control flow may require manual review.",
                ),
                suggested_experiments=(
                    "Review the resolved boundary and its cleanup on every exit path.",
                    "Capture repeated executions with the same recorded provenance. Changing treatment creates a separate experiment, not more baseline attempts.",
                ),
            ),
        )
    return tuple(findings)
