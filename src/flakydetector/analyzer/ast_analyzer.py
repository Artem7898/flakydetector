"""AST-based flaky pattern detection and Test Smells analysis in Python test code."""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flakydetector.models.domain import (
    ASTPattern,
    CodeLocation,
    FlakyCategory,
    FlakySeverity,
)
from flakydetector.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class PatternMatch:
    """Internal representation of a pattern match."""

    pattern_type: str
    category: FlakyCategory
    severity: FlakySeverity
    description: str
    line: int
    end_line: int | None
    node: ast.AST
    code_snippet: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


class FlakyPatternVisitor(ast.NodeVisitor):
    """AST visitor that detects flaky test patterns and test smells."""

    def __init__(self, source_lines: list[str], file_path: str) -> None:
        self._source_lines = source_lines
        self._file_path = file_path
        self._matches: list[PatternMatch] = []
        self._current_function: str | None = None
        self._current_class: str | None = None
        self._has_async = False

    @property
    def matches(self) -> list[PatternMatch]:
        return self._matches

    def _add_match(
        self,
        pattern_type: str,
        category: FlakyCategory,
        severity: FlakySeverity,
        description: str,
        node: ast.AST,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a pattern match."""
        snippet = self._get_code_snippet(node)
        self._matches.append(
            PatternMatch(
                pattern_type=pattern_type,
                category=category,
                severity=severity,
                description=description,
                line=node.lineno if hasattr(node, "lineno") else 1,
                end_line=node.end_lineno if hasattr(node, "end_lineno") else None,
                node=node,
                code_snippet=snippet,
                confidence=confidence,
                metadata=metadata or {},
            )
        )

    def _get_code_snippet(self, node: ast.AST, context_lines: int = 3) -> str:
        """Extract code snippet with context."""
        if not hasattr(node, "lineno"):
            return ""

        start = max(0, node.lineno - context_lines)
        end = min(len(self._source_lines), (node.end_lineno or node.lineno) + context_lines)
        lines = self._source_lines[start:end]
        return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines, start))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track class context."""
        prev_class = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = prev_class

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Detect async function definitions (potential race conditions)."""
        self._has_async = True
        prev_func = self._current_function
        self._current_function = node.name

        self._check_async_patterns(node)
        self._check_test_smells(node)  # Scientific expansion
        self.generic_visit(node)
        self._current_function = prev_func

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definitions and check for flaky patterns."""
        prev_func = self._current_function
        self._current_function = node.name

        self._check_timing_patterns(node)
        self._check_global_state_patterns(node)
        self._check_network_patterns(node)
        self._check_order_dependent_patterns(node)
        self._check_resource_leak_patterns(node)
        self._check_datetime_patterns(node)
        self._check_floating_point_patterns(node)
        self._check_test_smells(node)  # Scientific expansion

        self.generic_visit(node)
        self._current_function = prev_func

    def _check_async_patterns(self, node: ast.AsyncFunctionDef) -> None:
        """Check for async-related flaky patterns."""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func_name = self._get_call_name(child)
                if func_name == "asyncio.sleep":
                    self._add_match(
                        pattern_type="async_sleep",
                        category=FlakyCategory.ASYNC_RACE_CONDITION,
                        severity=FlakySeverity.MEDIUM,
                        description="asyncio.sleep in test - potential race condition",
                        node=child,
                        confidence=0.75,
                        metadata={"call": func_name},
                    )
                elif func_name in (
                    "gather", "asyncio.gather",
                    "Task", "asyncio.Task",
                    "create_task", "asyncio.create_task"
                ):
                    self._add_match(
                        pattern_type="concurrent_tasks",
                        category=FlakyCategory.ASYNC_RACE_CONDITION,
                        severity=FlakySeverity.HIGH,
                        description="Concurrent task execution without synchronization",
                        node=child,
                        confidence=0.85,
                        metadata={"call": func_name},
                    )

    def _check_timing_patterns(self, node: ast.FunctionDef) -> None:
        """Check for timing-dependent patterns."""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func_name = self._get_call_name(child)

                if func_name == "time.sleep":
                    self._add_match(
                        pattern_type="time_sleep",
                        category=FlakyCategory.TIMING_DEPENDENCY,
                        severity=FlakySeverity.MEDIUM,
                        description="time.sleep in test - timing dependency",
                        node=child,
                        confidence=0.9,
                        metadata={"sleep_call": func_name},
                    )

                if isinstance(child.func, ast.Attribute) and child.func.attr == "assertAlmostEqual":
                    self._add_match(
                        pattern_type="float_comparison",
                        category=FlakyCategory.FLOATING_POINT,
                        severity=FlakySeverity.LOW,
                        description="Float comparison - potential precision issues",
                        node=child,
                        confidence=0.6,
                    )

    def _check_global_state_patterns(self, node: ast.FunctionDef) -> None:
        """Check for global state mutation patterns."""
        global_names: set[str] = set()

        for stmt in node.body:
            if isinstance(stmt, ast.Global):
                global_names.update(stmt.names)

        if global_names:
            for child in ast.walk(node):
                # Handle both Assign (x = 1) and AugAssign (x += 1)
                if isinstance(child, (ast.Assign, ast.AugAssign)):
                    target = child.targets[0] if isinstance(child, ast.Assign) else child.target

                    if isinstance(target, ast.Name) and target.id in global_names:
                        self._add_match(
                            pattern_type="global_mutation",
                            category=FlakyCategory.GLOBAL_STATE,
                            severity=FlakySeverity.HIGH,
                            description=f"Mutation of global variable '{target.id}'",
                            node=child,
                            confidence=0.95,
                            metadata={"variable": target.id},
                        )

    def _check_network_patterns(self, node: ast.FunctionDef) -> None:
        """Check for network-dependent patterns."""
        # Check decorators FIRST to determine mocking context
        is_mocked = False
        if hasattr(node, 'decorator_list') and node.decorator_list:
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call):
                    dec_name = self._get_call_name(dec)
                    if 'patch' in dec_name or 'mock' in dec_name:
                        is_mocked = True
                        break

        network_indicators = {
            "requests.get": "HTTP GET",
            "requests.post": "HTTP POST",
            "requests.put": "HTTP PUT",
            "requests.delete": "HTTP DELETE",
            "httpx.get": "HTTP GET",
            "httpx.post": "HTTP POST",
            "urlopen": "URL open",
            "socket.connect": "Socket connect",
        }

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func_name = self._get_call_name(child)
                if func_name in network_indicators:
                    base_confidence = 0.2 if is_mocked else 0.8
                    base_severity = FlakySeverity.LOW if is_mocked else FlakySeverity.HIGH

                    self._add_match(
                        pattern_type="network_call",
                        category=FlakyCategory.NETWORK_DEPENDENCY,
                        severity=base_severity,
                        description=f"{network_indicators[func_name]} {'(mocked, low risk)' if is_mocked else 'without mocking'}",
                        node=child,
                        confidence=base_confidence,
                        metadata={"network_call": func_name, "is_mocked": is_mocked},
                    )

    def _check_order_dependent_patterns(self, node: ast.FunctionDef) -> None:
        """Check for order-dependent patterns."""
        for child in ast.walk(node):
            if isinstance(child, ast.For):
                if isinstance(child.iter, ast.Name):
                    self._add_match(
                        pattern_type="dict_iteration",
                        category=FlakyCategory.NON_DETERMINISTIC_ORDER,
                        severity=FlakySeverity.LOW,
                        description="Potential dict iteration without ordering",
                        node=child,
                        confidence=0.4,
                    )

            if isinstance(child, ast.Call):
                func_name = self._get_call_name(child)
                if func_name == "set" and "assert" in ast.dump(child):
                    self._add_match(
                        pattern_type="set_in_assertion",
                        category=FlakyCategory.NON_DETERMINISTIC_ORDER,
                        severity=FlakySeverity.MEDIUM,
                        description="Set usage in assertion - non-deterministic order",
                        node=child,
                        confidence=0.7,
                    )

    def _check_resource_leak_patterns(self, node: ast.FunctionDef) -> None:
        """Check for resource leak patterns."""
        has_context_manager = False
        has_open_call = False

        for child in ast.walk(node):
            if isinstance(child, ast.With):
                has_context_manager = True
            if isinstance(child, ast.Call):
                func_name = self._get_call_name(child)
                if func_name == "open":
                    has_open_call = True

        if has_open_call and not has_context_manager:
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func_name = self._get_call_name(child)
                    if func_name == "open":
                        self._add_match(
                            pattern_type="file_without_context",
                            category=FlakyCategory.RESOURCE_LEAK,
                            severity=FlakySeverity.MEDIUM,
                            description="open() without context manager - potential leak",
                            node=child,
                            confidence=0.85,
                        )

    def _check_datetime_patterns(self, node: ast.FunctionDef) -> None:
        """Check for datetime-dependent patterns."""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func_name = self._get_call_name(child)
                if func_name in ("datetime.now", "datetime.utcnow", "time.time"):
                    self._add_match(
                        pattern_type="datetime_now",
                        category=FlakyCategory.DATE_TIME_DEPENDENCY,
                        severity=FlakySeverity.MEDIUM,
                        description=f"{func_name}() - non-deterministic datetime",
                        node=child,
                        confidence=0.9,
                        metadata={"datetime_call": func_name},
                    )

    def _check_floating_point_patterns(self, node: ast.FunctionDef) -> None:
        """Check for floating-point precision patterns."""
        for child in ast.walk(node):
            if isinstance(child, ast.Compare):
                for op in child.ops:
                    if isinstance(op, (ast.Eq, ast.NotEq)):
                        for comparator in child.comparators:
                            if isinstance(comparator, ast.Constant) and isinstance(comparator.value, float):
                                self._add_match(
                                    pattern_type="float_equality",
                                    category=FlakyCategory.FLOATING_POINT,
                                    severity=FlakySeverity.MEDIUM,
                                    description="Direct float equality comparison",
                                    node=child,
                                    confidence=0.95,
                                )

    def _check_test_smells(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Deep expansion: Detect Test Smells like High Cyclomatic Complexity."""
        complexity = 1  # Base complexity

        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.ExceptHandler, ast.With)):
                complexity += 1
            elif isinstance(child, ast.For):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                # and/or operators add branches
                complexity += len(child.values) - 1
            elif isinstance(child, ast.Assert):
                complexity += 1

        # Scientific threshold: Tests with complexity > 10 are highly prone to flakiness
        if complexity > 10:
            self._add_match(
                pattern_type="high_complexity",
                category=FlakyCategory.UNKNOWN,
                severity=FlakySeverity.MEDIUM,
                description=f"High cyclomatic complexity ({complexity}). Complex tests often hide state dependencies.",
                node=node,
                confidence=0.7,
                metadata={"complexity_score": complexity},
            )

    def _get_call_name(self, node: ast.Call) -> str:
        """Extract full call name from Call node (e.g., 'requests.get')."""
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


class ASTAnalyzer:
    """Main AST analyzer for flaky test detection."""

    def __init__(self, max_file_size: int = 1_000_000) -> None:
        self._max_file_size = max_file_size
        self._pattern_stats: dict[str, int] = defaultdict(int)

    def analyze_file(self, file_path: Path) -> list[ASTPattern]:
        """Analyze a single Python file for flaky patterns."""
        logger.info("analyzing_file", path=str(file_path))

        if not file_path.exists():
            logger.warning("file_not_found", path=str(file_path))
            return []

        if file_path.stat().st_size > self._max_file_size:
            logger.warning("file_too_large", path=str(file_path), size=file_path.stat().st_size)
            return []

        try:
            source = file_path.read_text(encoding="utf-8")
            return self.analyze_source(source, str(file_path))
        except UnicodeDecodeError:
            logger.error("encoding_error", path=str(file_path))
            return []
        except Exception as e:
            logger.error("analysis_error", path=str(file_path), error=str(e))
            return []

    def analyze_source(self, source: str, file_path: str) -> list[ASTPattern]:
        """Analyze source code string for flaky patterns."""
        source_lines = source.splitlines()

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as e:
            logger.warning("syntax_error", path=file_path, error=str(e))
            return []

        visitor = FlakyPatternVisitor(source_lines, file_path)
        visitor.visit(tree)

        patterns = []
        for match in visitor.matches:
            self._pattern_stats[match.pattern_type] += 1

            patterns.append(
                ASTPattern(
                    pattern_type=match.pattern_type,
                    category=match.category,
                    severity=match.severity,
                    description=match.description,
                    location=CodeLocation(
                        file_path=file_path,
                        line_start=match.line,
                        line_end=match.end_line,
                        function_name=visitor._current_function,
                        class_name=visitor._current_class,
                    ),
                    code_snippet=match.code_snippet,
                    confidence=match.confidence,
                    metadata=match.metadata,
                )
            )

        logger.info(
            "analysis_complete",
            path=file_path,
            patterns_found=len(patterns),
        )

        return patterns

    def analyze_directory(
        self,
        directory: Path,
        pattern: str = "**/test_*.py",
        exclude: set[str] | None = None,
    ) -> dict[str, list[ASTPattern]]:
        """Analyze all test files in a directory."""
        results: dict[str, list[ASTPattern]] = {}
        exclude = exclude or {"venv", ".venv", "__pycache__", ".git", "node_modules"}

        for file_path in directory.rglob(pattern):
            if any(excl in file_path.parts for excl in exclude):
                continue

            patterns = self.analyze_file(file_path)
            if patterns:
                results[str(file_path)] = patterns

        logger.info(
            "directory_analysis_complete",
            directory=str(directory),
            files_with_patterns=len(results),
            total_patterns=sum(len(p) for p in results.values()),
        )

        return results

    def get_pattern_stats(self) -> dict[str, int]:
        """Get statistics about detected patterns."""
        return dict(self._pattern_stats)