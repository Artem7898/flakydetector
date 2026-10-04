"""Lexical helpers shared by the AST and fixture adapters."""

from __future__ import annotations

import ast
from collections.abc import Iterator

Function = ast.FunctionDef | ast.AsyncFunctionDef


def scope_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """Visit one lexical scope; nested definitions are not part of its body."""
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from scope_nodes(child)


def dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


def imports(node: ast.AST) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in scope_nodes(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                result[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(child, ast.ImportFrom) and child.module:
            for alias in child.names:
                result[alias.asname or alias.name] = f"{child.module}.{alias.name}"
    return result


def resolve(node: ast.AST, bindings: dict[str, str]) -> str:
    name = dotted(node)
    root, _, tail = name.partition(".")
    base = bindings.get(root, root)
    return f"{base}.{tail}" if tail and base else base


def string_args(node: ast.Call) -> tuple[str, ...]:
    return tuple(
        a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)
    )


def parameter_names(node: Function, aliases: dict[str, str]) -> set[str]:
    names: set[str] = set()
    for dec in node.decorator_list:
        if (
            isinstance(dec, ast.Call)
            and resolve(dec.func, aliases).endswith("mark.parametrize")
            and dec.args
        ):
            arg = dec.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                names.update(x.strip() for x in arg.value.split(","))
            elif isinstance(arg, (ast.Tuple, ast.List)):
                names.update(
                    x.value
                    for x in arg.elts
                    if isinstance(x, ast.Constant) and isinstance(x.value, str)
                )
    return names


def requested_fixtures(node: Function, aliases: dict[str, str]) -> tuple[str, ...]:
    params = parameter_names(node, aliases)
    names = [
        a.arg
        for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        if a.arg not in {"self", "cls"} | params
    ]
    injected = 0
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            target = resolve(dec.func, aliases)
            arity = 2 if target.endswith(".patch.object") or target == "patch.object" else 1
            if (
                target
                in {"patch", "unittest.mock.patch", "patch.object", "unittest.mock.patch.object"}
                and len(dec.args) == arity
                and not any(k.arg == "new" for k in dec.keywords)
            ):
                injected += 1
    names = names[injected:]
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and resolve(dec.func, aliases).endswith("mark.usefixtures"):
            names.extend(string_args(dec))
    return tuple(dict.fromkeys(names))
