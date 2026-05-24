"""Static analysis of pytest fixtures for shared state detection."""

from __future__ import annotations

import ast
from typing import Any

from flakydetector.models.domain import FixtureInfo
from flakydetector.utils.logger import get_logger

logger = get_logger(__name__)


class FixtureParser:
    """Parses Python files to extract pytest fixture metadata."""

    def parse_source(self, source: str, file_path: str) -> list[FixtureInfo]:
        """Parse source code and return list of detected fixtures."""
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            logger.warning("syntax_error", file=file_path)
            return []

        fixtures: list[FixtureInfo] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                info = self._analyze_fixture(node)
                if info:
                    fixtures.append(info)

        logger.info(
            "analysis_complete",
            path=file_path,
            fixtures_found=len(fixtures),
        )

        return fixtures

    def _analyze_fixture(
        self,
        node: ast.FunctionDef,
    ) -> FixtureInfo | None:
        """Check if function is pytest.fixture and extract metadata."""

        is_fixture = False
        scope = "function"
        autouse = False

        for dec in node.decorator_list:

            # @pytest.fixture(...)
            if isinstance(dec, ast.Call):
                func_name = self._get_call_name(dec)

                if func_name in ("pytest.fixture", "fixture"):
                    is_fixture = True

                    for keyword in dec.keywords:

                        if (
                            keyword.arg == "scope"
                            and isinstance(keyword.value, ast.Constant)
                        ):
                            scope = str(keyword.value.value)

                        if (
                            keyword.arg == "autouse"
                            and isinstance(keyword.value, ast.Constant)
                        ):
                            autouse = bool(keyword.value.value)

            # @pytest.fixture
            elif isinstance(dec, ast.Attribute):
                if dec.attr == "fixture":
                    is_fixture = True

        if not is_fixture:
            return None

        has_yield = self._contains_yield(node)
        uses_finalizer = self._contains_addfinalizer(node)
        returns_mutable = self._returns_mutable_literal(node)

        return FixtureInfo(
            fixture_name=node.name,
            scope=scope,
            has_yield=has_yield,
            has_autouse=autouse,
            returns_mutable_literal=returns_mutable,
            uses_finalizer=uses_finalizer,
            line=getattr(node, "lineno", 0),
        )

    def _contains_yield(self, node: ast.FunctionDef) -> bool:
        """Detect yield/yield from usage."""
        for child in ast.walk(node):
            if isinstance(child, (ast.Yield, ast.YieldFrom)):
                return True
        return False

    def _contains_addfinalizer(self, node: ast.FunctionDef) -> bool:
        """Detect request.addfinalizer(...) usage."""

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                name = self._get_call_name(child)

                # safer than `in`
                if name.endswith("addfinalizer"):
                    return True

        return False

    def _returns_mutable_literal(self, node: ast.FunctionDef) -> bool:
        """Detect return [], {}, set()."""

        if not node.body:
            return False

        last_stmt = node.body[-1]

        if not isinstance(last_stmt, ast.Return):
            return False

        value = last_stmt.value

        return isinstance(
            value,
            (
                ast.List,
                ast.Dict,
                ast.Set,
            ),
        )

    def _get_call_name(self, node: ast.Call) -> str:
        """Resolve fully-qualified call name."""

        if isinstance(node.func, ast.Name):
            return node.func.id

        if isinstance(node.func, ast.Attribute):
            parts: list[str] = []

            current: Any = node.func

            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value

            if isinstance(current, ast.Name):
                parts.append(current.id)

            return ".".join(reversed(parts))

        return ""