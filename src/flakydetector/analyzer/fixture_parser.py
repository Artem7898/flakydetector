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
            return []

        fixtures = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                info = self._analyze_fixture(node)
                if info:
                    fixtures.append(info)

        return fixtures

    def _analyze_fixture(self, node: ast.FunctionDef) -> FixtureInfo | None:
        """Check if a function is a pytest.fixture and extract its properties."""
        is_fixture = False
        scope = "function"
        autouse = False

        # 1. Ищем декоратор @pytest.fixture
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                func_name = self._get_call_name(dec)
                if func_name in ("pytest.fixture", "fixture"):
                    is_fixture = True
                    # Парсим аргументы: scope="session", autouse=True
                    for keyword in dec.keywords:
                        if keyword.arg == "scope" and isinstance(keyword.value, ast.Constant):
                            scope = keyword.value.value
                        if keyword.arg == "autouse" and isinstance(keyword.value, ast.Constant):
                            autouse = keyword.value.value
            elif isinstance(dec, ast.Attribute):
                if dec.attr == "fixture":
                    is_fixture = True

        if not is_fixture:
            return None

        # 2. Ищем yield (teardown)
        has_yield = self._contains_yield(node)

        # 3. Ищем addfinalizer
        uses_finalizer = self._contains_addfinalizer(node)

        # 4. Ищем возврат мутабельных литералов (return [], {})
        returns_mutable = self._returns_mutable_literal(node)

        return FixtureInfo(
            fixture_name=node.name,
            scope=scope,
            has_yield=has_yield,
            has_autouse=autouse,
            returns_mutable_literal=returns_mutable,
            uses_finalizer=uses_finalizer,
            line=node.lineno if hasattr(node, "lineno") else 0
        )

    def _contains_yield(self, node: ast.FunctionDef) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Yield) or isinstance(child, ast.YieldFrom):
                return True
        return False

    def _contains_addfinalizer(self, node: ast.FunctionDef) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                name = self._get_call_name(child)
                if "addfinalizer" in name:
                    return True
        return False

    def _returns_mutable_literal(self, node: ast.FunctionDef) -> bool:
        """Check if the fixture ends with `return []` or `return {}`."""
        if not node.body:
            return False
        last_stmt = node.body[-1]
        if isinstance(last_stmt, ast.Return) and isinstance(last_stmt.value, ast.List):
            return True
        if isinstance(last_stmt, ast.Return) and isinstance(last_stmt.value, ast.Dict):
            return True
        if isinstance(last_stmt, ast.Return) and isinstance(last_stmt.value, ast.Set):
            return True
        return False

    def _get_call_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            parts = []
            current = node.func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return ""