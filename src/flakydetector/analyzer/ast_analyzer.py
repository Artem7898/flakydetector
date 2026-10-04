"""Bounded source analysis. Each AST node is attributed in its lexical context."""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from flakydetector.analyzer.fixture_parser import FixtureParser
from flakydetector.analyzer.syntax import (
    Function,
    dotted,
    imports,
    requested_fixtures,
    resolve,
    scope_nodes,
    string_args,
)
from flakydetector.models.domain import (
    AnalysisDiagnostic,
    ASTPattern,
    CodeLocation,
    SourceAnalysis,
    TestDefinition,
)
from flakydetector.models.domain import (
    FlakyCategory as C,
)
from flakydetector.models.domain import (
    FlakySeverity as S,
)

MUTATORS = {
    "append",
    "extend",
    "insert",
    "remove",
    "pop",
    "clear",
    "update",
    "setdefault",
    "add",
    "discard",
    "sort",
    "reverse",
}
NETWORK = {
    "requests.get",
    "requests.post",
    "requests.put",
    "requests.patch",
    "requests.delete",
    "httpx.get",
    "httpx.post",
    "urllib.request.urlopen",
    "urlopen",
    "socket.connect",
}
EXCLUDE = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"}


@dataclass(slots=True, kw_only=True)
class Scope:
    name: str
    aliases: dict[str, str]
    globals: set[str] = field(default_factory=lambda: set[str]())
    locals: set[str] = field(default_factory=lambda: set[str]())
    mocks: set[str] = field(default_factory=lambda: set[str]())
    sets: set[str] = field(default_factory=lambda: set[str]())
    direct_imports: set[str] = field(default_factory=lambda: set[str]())


class FlakyPatternVisitor(ast.NodeVisitor):
    def __init__(
        self, tree: ast.Module, source: str, path: str, complexity_threshold: int = 10
    ) -> None:
        self.path = path
        self.lines = source.splitlines()
        self.matches: list[ASTPattern] = []
        self.tests: list[TestDefinition] = []
        self.scopes = [Scope(name="", aliases=imports(tree))]
        # A from-import binds a callable in this module; patching the source module
        # afterwards does not replace that binding. Do not conflate origin with lookup.
        self.module_from_imports = {
            alias.asname or alias.name
            for node in scope_nodes(tree) if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        module_path = PurePosixPath(path.replace("\\", "/")).with_suffix("")
        self.module_name = ".".join(part for part in module_path.parts if part not in {"/", "."})
        self.classes: list[str] = []
        self.collectible_classes: list[bool] = []
        self.protected_open: set[int] = set()
        self.module_names = {
            n.id
            for n in scope_nodes(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
        }
        self.complexity_threshold = complexity_threshold

    @property
    def current(self) -> Scope:
        return self.scopes[-1]

    def add(
        self,
        node: ast.AST,
        kind: str,
        category: C,
        severity: S,
        description: str,
        confidence: float,
        fix: str,
        **metadata: str | bool | int,
    ) -> None:
        if not isinstance(node, (ast.expr, ast.stmt)):
            return
        line = int(node.lineno)
        end = getattr(node, "end_lineno", None)
        self.matches.append(
            ASTPattern(
                pattern_type=kind,
                category=category,
                severity=severity,
                description=description,
                confidence=confidence,
                fix_suggestion=fix,
                location=CodeLocation(
                    file_path=self.path,
                    line_start=line,
                    line_end=end,
                    function_name=self.current.name or None,
                    class_name=".".join(self.classes) or None,
                ),
                code_snippet="\n".join(
                    self.lines[max(0, line - 2) : min(len(self.lines), (end or line) + 1)]
                ),
                metadata=dict(metadata),
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(node.name)
        # This is static discovery under the default pytest naming convention,
        # not a claim that collection/imports/custom hooks have been executed.
        enabled = node.name.startswith("Test") and not any(
            isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and child.name in {"__init__", "__new__"} for child in node.body
        ) and not any(
            isinstance(child, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__test__"
                for target in child.targets
            ) and isinstance(child.value, ast.Constant) and child.value.value is False
            for child in node.body
        )
        self.collectible_classes.append(enabled and all(self.collectible_classes))
        for child in node.body:
            self.visit(child)
        self.collectible_classes.pop()
        self.classes.pop()

    def _function(self, node: Function) -> None:
        parent = self.current
        aliases = {**parent.aliases, **imports(node)}
        nodes = tuple(scope_nodes(node))
        global_names = {name for n in nodes if isinstance(n, ast.Global) for name in n.names}
        locals_ = {
            n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
        } - global_names
        locals_.update(
            a.arg for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        )
        for name in locals_:
            aliases[name] = ""  # Do not treat a shadowed imported module as the module.
        aliases.update(imports(node))
        scope = Scope(
            name=f"{parent.name}.{node.name}" if parent.name else node.name,
            aliases=aliases,
            globals=global_names,
            locals=locals_,
            direct_imports={
                alias.asname or alias.name
                for child in nodes if isinstance(child, ast.ImportFrom)
                for alias in child.names
            },
        )
        for dec in node.decorator_list:
            scope.mocks.update(self._patch_targets(dec))
        is_fixture = any(
            resolve(dec.func if isinstance(dec, ast.Call) else dec, parent.aliases)
            in {"pytest.fixture", "pytest_asyncio.fixture", "fixture"}
            for dec in node.decorator_list
        )
        if (
            node.name.startswith("test") and not parent.name and not is_fixture
            and all(self.collectible_classes)
        ):
            self.tests.append(
                TestDefinition(
                    name=node.name,
                    class_name=".".join(self.classes) or None,
                    line=node.lineno,
                    fixtures=requested_fixtures(node, aliases),
                )
            )
        self.scopes.append(scope)
        complexity = 1 + sum(
            isinstance(
                n,
                (
                    ast.If,
                    ast.IfExp,
                    ast.For,
                    ast.AsyncFor,
                    ast.While,
                    ast.ExceptHandler,
                    ast.comprehension,
                ),
            )
            for n in nodes
        )
        complexity += sum(len(n.values) - 1 for n in nodes if isinstance(n, ast.BoolOp))
        complexity += sum(max(0, len(n.cases) - 1) for n in nodes if isinstance(n, ast.Match))
        if complexity > self.complexity_threshold:
            self.add(
                node,
                "high_complexity",
                C.UNKNOWN,
                S.LOW,
                f"Branch complexity {complexity}; maintainability signal, not observed flakiness",
                0.7,
                "Split independent behaviors into focused tests",
                complexity_score=complexity,
            )
        for child in node.body:
            self.visit(child)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def _patch_targets(self, node: ast.AST) -> set[str]:
        if not isinstance(node, ast.Call):
            return set()
        name = resolve(node.func, self.current.aliases)
        if name in {"patch", "unittest.mock.patch", "mock.patch", "mocker.patch"}:
            return set(string_args(node)[:1])
        if (
            name in {"patch.object", "unittest.mock.patch.object", "mock.patch.object"}
            and len(node.args) >= 2
        ):
            target, attr = node.args[:2]
            if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                return {f"{resolve(target, self.current.aliases)}.{attr.value}"}
        return set()

    def _with(self, node: ast.With | ast.AsyncWith) -> None:
        old_mocks = self.current.mocks.copy()
        old_protected = self.protected_open.copy()
        for item in node.items:
            self.current.mocks.update(self._patch_targets(item.context_expr))
            expr = item.context_expr
            if isinstance(expr, ast.Call):
                name = resolve(expr.func, self.current.aliases)
                if name in {"open", "builtins.open"}:
                    self.protected_open.add(id(expr))
                elif name in {"contextlib.closing", "closing"}:
                    self.protected_open.update(
                        id(n)
                        for n in ast.walk(expr)
                        if isinstance(n, ast.Call)
                        and resolve(n.func, self.current.aliases) in {"open", "builtins.open"}
                    )
            self.visit(item.context_expr)
        for stmt in node.body:
            self.visit(stmt)
        self.current.mocks = old_mocks
        self.protected_open = old_protected

    def visit_With(self, node: ast.With) -> None:
        self._with(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._with(node)

    def _mock_applies(self, function: ast.AST, origin: str) -> bool:
        if isinstance(function, ast.Name):
            if function.id in self.current.direct_imports:
                # Local imports may capture a patched value depending on control flow.
                # Until import timing is modeled, do not suppress a risk on this basis.
                return False
            if function.id in self.module_from_imports:
                return f"{self.module_name}.{function.id}" in self.current.mocks
        return origin in self.current.mocks

    def visit_Call(self, node: ast.Call) -> None:
        name = resolve(node.func, self.current.aliases)
        raw_name = dotted(node.func)
        if (
            raw_name in {"monkeypatch.setattr", "mocker.patch"}
            and raw_name.split(".")[0] in self.current.locals
        ):
            name = raw_name
        if self.current.name:
            if name in {"time.sleep", "asyncio.sleep"}:
                self.add(
                    node,
                    "async_sleep" if name == "asyncio.sleep" else "time_sleep",
                    C.ASYNC_RACE_CONDITION if name == "asyncio.sleep" else C.TIMING_DEPENDENCY,
                    S.MEDIUM,
                    f"{name}: inspect reliance on elapsed time",
                    0.9,
                    "Use explicit completion conditions; a delay alone does not prove flakiness",
                )
            elif name in {"asyncio.gather", "asyncio.create_task", "asyncio.Task"}:
                self.add(
                    node,
                    "concurrent_tasks",
                    C.ASYNC_RACE_CONDITION,
                    S.LOW,
                    "Concurrent scheduling; a race requires additional shared-state evidence",
                    0.55,
                    "Check shared state and await task completion",
                )
            elif name in NETWORK:
                mocked = self._mock_applies(node.func, name)
                self.add(
                    node,
                    "network_call",
                    C.NETWORK_DEPENDENCY,
                    S.LOW if mocked else S.HIGH,
                    f"{name}: " + ("matching mock found" if mocked else "external dependency"),
                    0.2 if mocked else 0.8,
                    "Use controlled responses for unit tests; isolate integration dependencies",
                    network_call=name,
                    is_mocked=mocked,
                )
            elif (
                name
                in {
                    "datetime.now",
                    "datetime.utcnow",
                    "datetime.datetime.now",
                    "datetime.datetime.utcnow",
                    "time.time",
                }
                and not self._mock_applies(node.func, name)
            ):
                self.add(
                    node,
                    "datetime_now",
                    C.DATE_TIME_DEPENDENCY,
                    S.MEDIUM,
                    f"{name}: wall-clock dependency",
                    0.9,
                    "Inject a clock or freeze time",
                )
            elif name in {"open", "builtins.open"} and id(node) not in self.protected_open:
                self.add(
                    node,
                    "file_without_context",
                    C.RESOURCE_LEAK,
                    S.MEDIUM,
                    "File acquisition without a matching context manager",
                    0.85,
                    "Use with open(...) or contextlib.closing",
                )
            if isinstance(node.func, ast.Attribute):
                root = node.func.value
                if (
                    isinstance(root, ast.Name)
                    and root.id in self.module_names
                    and root.id not in self.current.locals
                    and node.func.attr in MUTATORS
                ):
                    self.add(
                        node,
                        "global_mutation",
                        C.GLOBAL_STATE,
                        S.HIGH,
                        f"Mutation of module object {root.id}",
                        0.95,
                        "Use a per-test fixture or restore state",
                        variable=root.id,
                    )
            if name in {"monkeypatch.setattr", "mocker.patch"}:
                if name == "mocker.patch":
                    self.current.mocks.update(string_args(node)[:1])
                elif (
                    node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    self.current.mocks.add(node.args[0].value)
                elif (
                    len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                ):
                    self.current.mocks.add(
                        f"{resolve(node.args[0], self.current.aliases)}.{node.args[1].value}"
                    )
        self.generic_visit(node)

    def _assignment(self, node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> None:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            names = [n.id for n in ast.walk(target) if isinstance(n, ast.Name)]
            for name in names:
                if self.current.name and (
                    name in self.current.globals
                    or (
                        not isinstance(target, ast.Name)
                        and name in self.module_names
                        and name not in self.current.locals
                    )
                ):
                    self.add(
                        node,
                        "global_mutation",
                        C.GLOBAL_STATE,
                        S.HIGH,
                        f"Mutation of module variable {name}",
                        0.95,
                        "Isolate or restore shared state",
                        variable=name,
                    )
            if (
                isinstance(target, ast.Name)
                and isinstance(node.value, (ast.Set, ast.SetComp))
                or isinstance(target, ast.Name)
                and isinstance(node.value, ast.Call)
                and resolve(node.value.func, self.current.aliases) == "set"
            ):
                self.current.sets.add(target.id)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._assignment(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._assignment(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._assignment(node)

    def visit_For(self, node: ast.For) -> None:
        if (
            self.current.name
            and isinstance(node.iter, ast.Name)
            and any(node.iter.id in s.sets for s in self.scopes)
        ):
            self.add(
                node,
                "dict_iteration",
                C.NON_DETERMINISTIC_ORDER,
                S.LOW,
                "Iteration over a known set (legacy feature name); order dependency needs verification",
                0.65,
                "Sort only when order is part of the assertion",
            )
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        if (
            self.current.name
            and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)
            and any(
                isinstance(n, ast.Constant) and isinstance(n.value, float)
                for n in [node.left, *node.comparators]
            )
        ):
            self.add(
                node,
                "float_equality",
                C.FLOATING_POINT,
                S.LOW,
                "Exact float comparison: precision smell, not proof of intermittent failure",
                0.95,
                "Use pytest.approx or a justified exact comparison",
            )
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        for child in ast.walk(node.test):
            if (
                isinstance(child, ast.Call)
                and resolve(child.func, self.current.aliases) in {"list", "tuple"}
                and child.args
            ):
                arg = child.args[0]
                if isinstance(arg, ast.Set) or (
                    isinstance(arg, ast.Call) and resolve(arg.func, self.current.aliases) == "set"
                ):
                    self.add(
                        child,
                        "set_in_assertion",
                        C.NON_DETERMINISTIC_ORDER,
                        S.MEDIUM,
                        "Unordered set converted to an ordered assertion value",
                        0.8,
                        "Compare sets or explicitly sort",
                    )
        self.generic_visit(node)


class ASTAnalyzer:
    def __init__(self, max_file_size: int = 1_000_000, max_nodes: int = 50_000) -> None:
        self.max_file_size = max_file_size
        self.max_nodes = max_nodes

    def analyze_source(self, source: str, file_path: str) -> SourceAnalysis:
        def failure(code: str, message: str, line: int | None = None) -> SourceAnalysis:
            return SourceAnalysis(
                file_path=file_path,
                diagnostics=(
                    AnalysisDiagnostic(code=code, message=message, file_path=file_path, line=line),
                ),
            )

        if len(source.encode("utf-8")) > self.max_file_size:
            return failure("file_too_large", "File exceeds the configured byte limit")
        try:
            tree = ast.parse(source, filename=file_path)
            if sum(1 for _ in ast.walk(tree)) > self.max_nodes:
                return failure("ast_too_large", "AST exceeds the configured node limit")
            visitor = FlakyPatternVisitor(tree, source, file_path)
            visitor.visit(tree)
            fixtures = FixtureParser().parse_tree(tree, file_path)
        except SyntaxError as exc:
            return failure("syntax_error", exc.msg, exc.lineno)
        except (RecursionError, ValueError) as exc:
            return failure("parse_error", str(exc))
        return SourceAnalysis(
            file_path=file_path,
            patterns=tuple(visitor.matches),
            fixtures=fixtures,
            tests=tuple(visitor.tests),
        )

    def analyze_file(self, file_path: Path) -> SourceAnalysis:
        try:
            with file_path.open("rb") as stream:
                raw = stream.read(self.max_file_size + 1)
            if len(raw) > self.max_file_size:
                raise ValueError("File exceeds the configured byte limit")
            return self.analyze_source(raw.decode("utf-8"), str(file_path))
        except (OSError, UnicodeError, ValueError) as exc:
            return SourceAnalysis(
                file_path=str(file_path),
                diagnostics=(
                    AnalysisDiagnostic(
                        code="read_error", message=str(exc), file_path=str(file_path)
                    ),
                ),
            )

    def analyze_directory(
        self, directory: Path, pattern: str = "**/test_*.py", exclude: set[str] | None = None
    ) -> dict[str, SourceAnalysis]:
        if not directory.is_dir():
            raise ValueError(f"Not a directory: {directory}")
        excluded = EXCLUDE if exclude is None else exclude
        return {
            str(p): self.analyze_file(p)
            for p in sorted(directory.glob(pattern))
            if not p.is_symlink() and not any(x in excluded for x in p.relative_to(directory).parts)
        }

    @staticmethod
    def pattern_stats(results: tuple[SourceAnalysis, ...]) -> dict[str, int]:
        return dict(Counter(p.pattern_type for result in results for p in result.patterns))
