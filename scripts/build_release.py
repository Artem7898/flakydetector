"""Allowlisted deterministic archive, with a manifest of exactly the shipped bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tomllib
import zipfile
from pathlib import Path

from check_release import MANIFEST, read_release, validate_entries

TOP = {
    "README.md", "README.RUS.md", "LICENSE", "CHANGELOG.md", "pyproject.toml", "uv.lock",
    "CITATION.cff", ".readthedocs.yaml",
    "Dockerfile", "compose.yaml", ".env.example", ".dockerignore", ".gitignore", ".pre-commit-config.yaml",
}
TREES = {"src", "tests", "scripts", "docs", ".github"}
FRONTEND = {"src", "package.json", "package-lock.json", "index.html", "vite.config.js"}
EXCLUDE = {"__pycache__", "_build", ".pytest_cache", ".ruff_cache", "node_modules", "static", ".venv"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", version):
        raise SystemExit("Unsafe release version")
    entries: list[tuple[str, bytes]] = []
    # Walk only allowed trees; do not recursively enumerate a local environment or .git.
    candidates = [root / name for name in TOP if (root / name).is_file()]
    for name in (*sorted(TREES), "dashboard_frontend"):
        for current, dirs, files in os.walk(root / name):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDE and not Path(current, d).is_symlink())
            candidates.extend(Path(current, file) for file in sorted(files))
    for path in sorted(candidates):
        if path.is_symlink():
            raise SystemExit(f"Refusing symlink: {path.relative_to(root)}")
        relative = path.relative_to(root)
        if relative.parts[0] == "dashboard_frontend" and (len(relative.parts) < 2 or relative.parts[1] not in FRONTEND):
            continue
        entries.append((relative.as_posix(), path.read_bytes()))
    try:
        validate_entries(entries, require_manifest=False)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    manifest = {"schema_version": 1, "version": version,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in entries}}
    entries.append((MANIFEST, (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries):
                info = zipfile.ZipInfo(f"flakydetector-{version}/" + name, date_time=(2025, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        read_release(temporary)
        temporary.replace(args.output)
    finally:
        temporary.unlink(missing_ok=True)
    checksum = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_name(args.output.name + ".sha256").write_text(f"{checksum}  {args.output.name}\n")
    print(f"Created {args.output.name}: {len(entries)} files; SHA-256 {checksum}")


if __name__ == "__main__":
    main()
