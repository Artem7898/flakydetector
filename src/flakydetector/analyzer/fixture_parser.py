"""Fixture definitions. Definitions and actual per-test usage remain distinct."""

from __future__ import annotations

import ast

from flakydetector.analyzer.syntax import (
    Function,
    imports,
    requested_fixtures,
    resolve,
    scope_nodes,
)
from flakydetector.models.domain import FixtureInfo


class FixtureParser:
    def parse_source(self, source: str, file_path: str) -> tuple[FixtureInfo, ...]:
        return self.parse_tree(ast.parse(source, filename=file_path), file_path)

    def parse_tree(self, tree: ast.Module, file_path: str) -> tuple[FixtureInfo, ...]:
        aliases = imports(tree)
        result: list[FixtureInfo] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                info = self._parse(node, aliases, file_path, None)
                if info:
                    result.append(info)
            elif isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        info = self._parse(method, aliases, file_path, node.name)
                        if info:
                            result.append(info)
        return tuple(result)

    def _parse(
        self, node: Function, aliases: dict[str, str], path: str, cls: str | None
    ) -> FixtureInfo | None:
        fixture_name, scope, autouse = node.name, "function", False
        found = False
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if resolve(target, aliases) not in {
                "pytest.fixture",
                "pytest_asyncio.fixture",
                "fixture",
            }:
                continue
            found = True
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    if kw.arg == "scope":
                        scope = (
                            kw.value.value
                            if isinstance(kw.value, ast.Constant)
                            and isinstance(kw.value.value, str)
                            else "dynamic"
                        )
                    elif kw.arg == "autouse" and isinstance(kw.value, ast.Constant):
                        autouse = kw.value.value is True
                    elif (
                        kw.arg == "name"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        fixture_name = kw.value.value
        if not found:
            return None
        nodes = tuple(scope_nodes(node))
        mutable = False
        for child in nodes:
            if isinstance(child, (ast.Return, ast.Yield)) and child.value is not None:
                value = child.value
                mutable |= isinstance(value, (ast.List, ast.Dict, ast.Set)) or (
                    isinstance(value, ast.Call)
                    and resolve(value.func, aliases) in {"list", "dict", "set"}
                )
        return FixtureInfo(
            fixture_name=fixture_name,
            function_name=node.name,
            scope=scope,
            has_yield=any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in nodes),
            has_autouse=autouse,
            returns_mutable_literal=mutable,
            uses_finalizer=any(
                isinstance(n, ast.Call) and resolve(n.func, aliases).endswith(".addfinalizer")
                for n in nodes
            ),
            line=node.lineno,
            file_path=path,
            class_name=cls,
            dependencies=requested_fixtures(node, aliases),
        )
