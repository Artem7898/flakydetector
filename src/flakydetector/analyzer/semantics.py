"""Selected intraprocedural rules. Unknown dynamic semantics are not causal evidence."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from pydantic import JsonValue

from flakydetector.analyzer.syntax import (
    Function,
    character_column,
    dotted,
    imports,
    resolve,
    scope_nodes,
)
from flakydetector.models.domain import ASTPattern, CodeLocation
from flakydetector.models.domain import FlakyCategory as C
from flakydetector.models.domain import FlakySeverity as S

CLIENTS = {
    "httpx.Client",
    "httpx.AsyncClient",
    "requests.Session",
    "requests.sessions.Session",
    "aiohttp.ClientSession",
}
HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "request"}
CACHE_CLIENTS = {"redis.Redis", "redis.StrictRedis", "pymemcache.client.base.Client"}
DB_CLIENTS = {"sqlalchemy.orm.Session", "sqlalchemy.orm.sessionmaker", "sqlite3.connect"}
RANDOM_CALLS = {
    "random.random",
    "random.randint",
    "random.choice",
    "random.randrange",
    "numpy.random.rand",
    "numpy.random.randn",
    "numpy.random.randint",
}


@dataclass
class State:
    types: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    controlled: set[str] = field(default_factory=lambda: set[str]())
    pending: dict[str, tuple[ast.AST, str]] = field(
        default_factory=lambda: dict[str, tuple[ast.AST, str]]()
    )
    random_values: set[str] = field(default_factory=lambda: set[str]())
    seeded: bool = False

    def copy(self) -> State:
        return State(
            self.types.copy(),
            self.controlled.copy(),
            self.pending.copy(),
            self.random_values.copy(),
            self.seeded,
        )

    def merge(self, other: State) -> State:
        return State(
            {k: v for k, v in self.types.items() if other.types.get(k) == v},
            self.controlled & other.controlled,
            {**self.pending, **other.pending},
            self.random_values | other.random_values,
            self.seeded and other.seeded,
        )


def enrich_patterns(
    tree: ast.Module, source: str, path: str, patterns: list[ASTPattern]
) -> list[ASTPattern]:
    result = list(patterns)
    module_aliases = imports(tree)
    lines = source.splitlines()

    def analyze(function: Function, qualified: str, class_name: str | None) -> None:
        nonlocal result
        aliases = {**module_aliases, **imports(function)}
        args = {
            a.arg
            for a in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        }
        for a in args:
            if a in aliases:
                aliases[a] = ""
        seeded = False
        nodes = tuple(scope_nodes(function))
        # Cleanup recognition is deliberately literal and tied to try/finally.
        restored_by_node: dict[int, set[str]] = {}
        saved: dict[str, str] = {}
        for st in function.body:
            if (
                isinstance(st, ast.Assign)
                and len(st.targets) == 1
                and isinstance(st.targets[0], ast.Name)
            ):
                saved[st.targets[0].id] = ast.dump(st.value)
            if isinstance(st, ast.Try) and st.finalbody:
                restored: set[str] = set()
                for cleanup in st.finalbody:
                    if isinstance(cleanup, ast.Expr) and isinstance(cleanup.value, ast.Call):
                        call = cleanup.value
                        if (
                            resolve(call.func, aliases) == "os.chdir"
                            and call.args
                            and isinstance(call.args[0], ast.Name)
                        ):
                            previous = saved.get(call.args[0].id, "")
                            if "getcwd" in previous:
                                restored.add("cwd")
                    if isinstance(cleanup, ast.Assign) and isinstance(cleanup.value, ast.Name):
                        for target in cleanup.targets:
                            # Match expression without Store/Load contexts.
                            old = saved.get(cleanup.value.id, "")
                            if old and old.replace("Load()", "Store()") == ast.dump(target).replace(
                                "Load()", "Store()"
                            ):
                                restored.add(
                                    dotted(target.value)
                                    if isinstance(target, ast.Subscript)
                                    else dotted(target),
                                )
                for protected in [*st.body, *st.handlers, *st.orelse, *st.finalbody]:
                    for child in ast.walk(protected):
                        restored_by_node.setdefault(id(child), set()).update(restored)
        shared_scope = False
        for dec in function.decorator_list:
            if isinstance(dec, ast.Call) and resolve(dec.func, aliases) in {
                "pytest.fixture",
                "pytest_asyncio.fixture",
            }:
                shared_scope = any(
                    (
                        k.arg == "scope"
                        and isinstance(k.value, ast.Constant)
                        and (k.value.value in {"session", "module", "class"})
                        for k in dec.keywords
                    ),
                )

        def add(
            node: ast.AST,
            kind: str,
            category: C,
            severity: S,
            description: str,
            fix: str,
            **meta: JsonValue,
        ) -> None:
            if not isinstance(node, (ast.expr, ast.stmt)):
                return
            line, end = (node.lineno, node.end_lineno or node.lineno)
            result.append(
                ASTPattern(
                    pattern_type=kind,
                    category=category,
                    severity=severity,
                    description=description,
                    confidence=0.8,
                    fix_suggestion=fix,
                    code_snippet="\n".join(lines[line - 1 : end]),
                    location=CodeLocation(
                        file_path=path,
                        line_start=line,
                        line_end=end,
                        column_start=character_column(
                            lines, line, getattr(node, "col_offset", None)
                        ),
                        column_end=character_column(
                            lines, end, getattr(node, "end_col_offset", None)
                        ),
                        function_name=qualified,
                        class_name=class_name,
                    ),
                    metadata=meta,
                ),
            )

        def call_type(call: ast.Call, state: State) -> str:
            name = resolve(call.func, {**aliases, **state.types})
            return name

        def inspect(expr: ast.AST, state: State) -> None:
            if isinstance(expr, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                return
            if isinstance(expr, ast.Call):
                name = call_type(expr, state)
                raw = dotted(expr.func)
                root_name = raw.split(".")[0]
                owner, _, method = name.rpartition(".")
                if (owner in CLIENTS and method in HTTP_METHODS) and (
                    root_name not in state.controlled
                ):
                    kw = next((k.value for k in expr.keywords if k.arg == "timeout"), None)
                    metadata: dict[str, JsonValue] = {
                        "network_call": name,
                        "is_mocked": False,
                    }
                    if (
                        isinstance(kw, ast.Constant)
                        and isinstance(kw.value, (int, float))
                        and (not isinstance(kw.value, bool))
                    ):
                        metadata["timeout_seconds"] = float(kw.value)
                    add(
                        expr,
                        "network_client_call",
                        C.NETWORK_DEPENDENCY,
                        S.HIGH,
                        f"{name}: no supported deterministic transport was resolved",
                        "Use a controlled transport; verify the network boundary in an isolated experiment",
                        **metadata,
                    )
                if name in {"random.seed", "numpy.random.seed"}:
                    state.seeded = True
                if name == "os.chdir" and "cwd" not in restored_by_node.get(id(expr), set()):
                    add(
                        expr,
                        "cwd_mutation",
                        C.GLOBAL_STATE,
                        S.MEDIUM,
                        "Process working directory changed without a supported restore",
                        "Use monkeypatch.chdir or save cwd and restore it in finally",
                    )
                if name in {"locale.setlocale", "time.tzset"}:
                    add(
                        expr,
                        "process_environment",
                        C.GLOBAL_STATE,
                        S.MEDIUM,
                        "Process locale/timezone mutation; restoration needs review",
                        "Restore process settings in a finally block; prefer process isolation",
                    )
                if (
                    owner in CACHE_CLIENTS
                    and method in {"set", "add", "incr", "hset"}
                    and expr.args
                    and isinstance(expr.args[0], ast.Constant)
                ):
                    add(
                        expr,
                        "fixed_cache_key",
                        C.GLOBAL_STATE,
                        S.MEDIUM,
                        "Cache write uses a fixed key; cross-test isolation is not established",
                        "Use a per-test namespace and cleanup; validate isolated backend configuration",
                    )
                if (
                    owner in DB_CLIENTS
                    and method in {"execute", "commit", "add", "flush"}
                    and shared_scope
                ):
                    rollback = any(
                        (
                            isinstance(n, ast.Try)
                            and any(
                                (id(child) == id(expr) for st in n.body for child in ast.walk(st))
                            )
                            and any(
                                (
                                    isinstance(st, ast.Expr)
                                    and isinstance(st.value, ast.Call)
                                    and (dotted(st.value.func) == root_name + ".rollback")
                                    for st in n.finalbody
                                ),
                            )
                            for n in nodes
                        ),
                    )
                    if not rollback:
                        add(
                            expr,
                            "shared_database",
                            C.GLOBAL_STATE,
                            S.MEDIUM,
                            "Shared-scope database fixture has writes without a visible rollback",
                            "Use an isolated transaction/DB and demonstrate reset across tests",
                        )
                if (
                    name in {"open", "builtins.open"}
                    and expr.args
                    and isinstance(expr.args[0], ast.Constant)
                    and isinstance(expr.args[0].value, str)
                ):
                    mode = (
                        expr.args[1].value
                        if len(expr.args) > 1 and isinstance(expr.args[1], ast.Constant)
                        else "r"
                    )
                    if isinstance(mode, str) and any(c in mode for c in "wax+"):
                        add(
                            expr,
                            "fixed_file_path",
                            C.FILE_SYSTEM,
                            S.MEDIUM,
                            "Write uses a literal filesystem path; closing is not path isolation",
                            "Use tmp_path or a unique per-test directory",
                        )
                if method == "start" and owner in {"threading.Thread", "multiprocessing.Process"}:
                    state.pending[root_name] = (expr, "background_worker")
                # join(timeout=...) does not establish termination.
                if (method == "join") and (not expr.args and (not expr.keywords)):
                    state.pending.pop(root_name, None)
            if isinstance(expr, ast.Await):
                if isinstance(expr.value, ast.Name):
                    state.pending.pop(expr.value.id, None)
                elif (
                    isinstance(expr.value, ast.Call)
                    and call_type(expr.value, state) == "asyncio.gather"
                ):
                    for arg in expr.value.args:
                        if isinstance(arg, ast.Name):
                            state.pending.pop(arg.id, None)
            for child in ast.iter_child_nodes(expr):
                inspect(child, state)

        def block(body: list[ast.stmt], state: State) -> State:
            for st in body:
                if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if isinstance(st, ast.If):
                    inspect(st.test, state)
                    if isinstance(st.test, ast.Constant):
                        state = block(st.body if st.test.value else st.orelse, state)
                    else:
                        state = block(st.body, state.copy()).merge(block(st.orelse, state.copy()))
                    continue
                if isinstance(st, (ast.For, ast.AsyncFor, ast.While)):
                    loop_nodes = list(scope_nodes(st))
                    if any(
                        (
                            isinstance(n, ast.Call)
                            and resolve(n.func, aliases) in {"time.sleep", "asyncio.sleep"}
                            for n in loop_nodes
                        ),
                    ):
                        add(
                            st,
                            "fixed_sleep_polling",
                            C.TIMING_DEPENDENCY,
                            S.MEDIUM,
                            "Polling loop contains time-based waiting; completion budget is not established",
                            "Wait for a condition with a monotonic deadline and retain timeout diagnostics",
                        )
                    state = state.merge(block(st.body, state.copy()))
                    state = block(st.orelse, state)
                    continue
                if isinstance(st, ast.Try):
                    # Success and exceptional paths conservatively join before finally.
                    success = block(st.body, state.copy())
                    success = block(st.orelse, success)
                    joined = success.merge(state)
                    for h in st.handlers:
                        joined = joined.merge(block(h.body, state.copy()))
                    state = block(st.finalbody, joined)
                    continue
                if isinstance(st, (ast.With, ast.AsyncWith)):
                    for item in st.items:
                        if isinstance(item.context_expr, ast.Call) and isinstance(
                            item.optional_vars, ast.Name
                        ):
                            constructor = call_type(item.context_expr, state)
                            state.types[item.optional_vars.id] = constructor
                            if constructor in CLIENTS:
                                transport = next(
                                    (
                                        k.value
                                        for k in item.context_expr.keywords
                                        if k.arg == "transport"
                                    ),
                                    None,
                                )
                                if isinstance(transport, ast.Call) and call_type(
                                    transport, state
                                ) in {
                                    "httpx.MockTransport",
                                    "httpx.ASGITransport",
                                    "httpx.WSGITransport",
                                }:
                                    state.controlled.add(item.optional_vars.id)
                        inspect(item.context_expr, state)
                    state = block(st.body, state)
                    continue
                if isinstance(st, (ast.Assign, ast.AnnAssign)):
                    value = st.value
                    targets = st.targets if isinstance(st, ast.Assign) else [st.target]
                    if value is not None:
                        inspect(value, state)
                        for t in targets:
                            if isinstance(t, ast.Name):
                                state.types.pop(t.id, None)
                                state.controlled.discard(t.id)
                                if isinstance(value, ast.Call):
                                    name = call_type(value, state)
                                    state.types[t.id] = name
                                    if name in {
                                        "asyncio.create_task",
                                        "asyncio.ensure_future",
                                        "asyncio.Task",
                                    }:
                                        state.pending[t.id] = (value, "orphan_task")
                                    if name in RANDOM_CALLS and (not state.seeded):
                                        state.random_values.add(t.id)
                                    if name in CLIENTS:
                                        transport = next(
                                            (
                                                k.value
                                                for k in value.keywords
                                                if k.arg == "transport"
                                            ),
                                            None,
                                        )
                                        controlled = (
                                            isinstance(transport, ast.Call)
                                            and call_type(transport, state)
                                            in {
                                                "httpx.MockTransport",
                                                "httpx.ASGITransport",
                                                "httpx.WSGITransport",
                                            }
                                            or (
                                                isinstance(transport, ast.Name)
                                                and state.types.get(transport.id)
                                                in {
                                                    "httpx.MockTransport",
                                                    "httpx.ASGITransport",
                                                    "httpx.WSGITransport",
                                                }
                                            )
                                        )
                                        if controlled:
                                            state.controlled.add(t.id)
                            elif (
                                isinstance(t, ast.Subscript)
                                and resolve(t.value, aliases) == "os.environ"
                                and ("os.environ" not in restored_by_node.get(id(st), set()))
                            ):
                                add(
                                    st,
                                    "environment_mutation",
                                    C.GLOBAL_STATE,
                                    S.MEDIUM,
                                    "Environment mapping is changed without a supported restore",
                                    "Use monkeypatch.setenv/delenv or a scoped restore",
                                )
                    continue
                if (isinstance(st, ast.Assert) and (not state.seeded)) and (
                    any(
                        isinstance(n, ast.Name)
                        and n.id in state.random_values
                        or (isinstance(n, ast.Call) and call_type(n, state) in RANDOM_CALLS)
                        for n in ast.walk(st.test)
                    )
                ):
                    add(
                        st,
                        "random_assertion",
                        C.NON_DETERMINISTIC_ORDER,
                        S.MEDIUM,
                        "Assertion depends on an uncontrolled random draw",
                        "Inject a deterministic generator/seed; preserve the seed as provenance",
                    )
                inspect(st, state)
                if isinstance(st, (ast.Return, ast.Raise)):
                    break
            return state

        state = block(function.body, State(seeded=seeded))
        for _, (node, kind) in sorted(state.pending.items()):
            add(
                node,
                kind,
                C.CONCURRENT_ACCESS,
                S.MEDIUM,
                "No guaranteed completion/cleanup of this background handle was resolved",
                "Await/join completion on every exit path; cancel then await tasks during cleanup",
            )
        # A zero-duration sleep yields to the loop; do not call it a timing wait.
        zero_lines = {
            (n.lineno, character_column(lines, n.lineno, n.col_offset))
            for n in nodes
            if isinstance(n, ast.Call)
            and resolve(n.func, aliases) == "asyncio.sleep"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and (n.args[0].value == 0)
        }
        result = [
            p
            for p in result
            if not (
                p.location.function_name == qualified
                and p.location.class_name == class_name
                and (p.pattern_type == "async_sleep")
                and ((p.location.line_start, p.location.column_start) in zero_lines)
            )
        ]

    def walk(body: list[ast.stmt], parents: str = "", cls: str | None = None) -> None:
        for st in body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{parents}.{st.name}" if parents else st.name
                analyze(st, name, cls)
                walk(st.body, name, cls)
            elif isinstance(st, ast.ClassDef):
                walk(st.body, parents, f"{cls}.{st.name}" if cls else st.name)

    walk(tree.body)
    unique: dict[tuple[str, int, int, str, str | None], ASTPattern] = {}
    for pattern in result:
        unique[
            pattern.pattern_type,
            pattern.location.line_start,
            pattern.location.column_start or 0,
            pattern.location.file_path,
            pattern.location.function_name,
        ] = pattern
    return list(unique.values())
