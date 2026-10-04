"""Validate final source-archive bytes, required inputs and a complete SHA-256 manifest.

Credential scanning is defense in depth, not proof of the absence of arbitrary secrets.
The manifest detects corruption/drift; it is not an authenticated publisher signature.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".pyright",
    "data",
    "catboost_info",
    "htmlcov",
}
CREDENTIALS = [
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{30,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
REQUIRED = {
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    "compose.yaml",
    "src/flakydetector/__init__.py",
    "src/flakydetector/cli.py",
    "src/flakydetector/dashboard/main.py",
    "scripts/wheel_smoke.py",
    "scripts/container_smoke.py",
    "scripts/build_release.py",
    "scripts/check_release.py",
    "dashboard_frontend/package.json",
    "dashboard_frontend/package-lock.json",
    "dashboard_frontend/index.html",
    "dashboard_frontend/src/App.jsx",
    "dashboard_frontend/src/contract.js",
    "dashboard_frontend/src/state.js",
    "dashboard_frontend/src/Results.jsx",
    "scripts/verify_release.py",
    "scripts/installed_wheel_smoke.py",
}
MANIFEST = "RELEASE_MANIFEST.json"


def inspect_entries(entries: list[tuple[str, bytes]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for name, data in entries:
        path = PurePosixPath(name)
        if name in seen:
            errors.append(f"Duplicate archive member: {name}")
        seen.add(name)
        if (
            path.is_absolute()
            or "\\" in name
            or ":" in name
            or any(part in {"..", ".", ""} for part in name.split("/"))
        ):
            errors.append(f"Unsafe archive path: {name}")
        if (
            any(part in FORBIDDEN_PARTS for part in path.parts)
            or path.suffix in {".db", ".cbm", ".pyc", ".pyo"}
            or path.name.startswith(".coverage")
            or path.name in {"coverage.xml", "coverage.json"}
            or (path.name.startswith(".env") and path.name != ".env.example")
        ):
            errors.append(f"Forbidden artifact: {name}")
        if any(regex.search(data) for regex in CREDENTIALS):
            errors.append(f"Credential-like content: {name}")
        if path.name == ".env.example":
            for line in data.decode().splitlines():
                key, sep, value = line.partition("=")
                if (
                    sep
                    and any(part in key.upper() for part in ["KEY", "TOKEN", "PASSWORD", "SECRET"])
                    and value.strip()
                ):
                    errors.append(f"Nonempty credential placeholder: {name}")
    return errors


def validate_entries(
    entries: list[tuple[str, bytes]], *, require_manifest: bool = True
) -> dict[str, bytes]:
    errors = inspect_entries(entries)
    first_parts = {name.split("/")[0] for name, _ in entries}
    prefix = (
        next(iter(first_parts)) + "/"
        if len(first_parts) == 1 and all("/" in name for name, _ in entries)
        else ""
    )
    files = {name.removeprefix(prefix): data for name, data in entries}
    errors.extend(f"Missing required file: {name}" for name in sorted(REQUIRED - files.keys()))
    if not errors:
        try:
            version = tomllib.loads(files["pyproject.toml"].decode())["project"]["version"]
            lock = tomllib.loads(files["uv.lock"].decode())
            local = [p for p in lock["package"] if p["name"] == "flakydetector"]
            if len(local) != 1 or local[0]["version"] != version:
                errors.append("Project version differs from uv.lock")
            if not files["LICENSE"].strip():
                errors.append("LICENSE is empty")
            if require_manifest:
                manifest = json.loads(files[MANIFEST])
                expected = {
                    name: hashlib.sha256(data).hexdigest()
                    for name, data in files.items()
                    if name != MANIFEST
                }
                if (
                    manifest.get("schema_version") != 1
                    or manifest.get("version") != version
                    or manifest.get("files") != expected
                ):
                    errors.append("Release manifest does not match final archive bytes")
        except (KeyError, ValueError, TypeError) as exc:
            errors.append(f"Invalid release metadata: {exc}")
    if errors:
        raise ValueError("\n".join(errors))
    return files


def read_release(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > 10000 or sum(member.file_size for member in members) > 100_000_000:
            raise ValueError("Source archive exceeds verification limits")
        if any(stat.S_ISLNK(member.external_attr >> 16) for member in members):
            raise ValueError("Symlinks are not allowed in source releases")
        return validate_entries(
            [(member.filename, archive.read(member)) for member in members if not member.is_dir()]
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        files = read_release(args.archive)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Release content/required-files/manifest gate passed: {len(files)} files")


if __name__ == "__main__":
    main()
