"""Execution fingerprints without importing pytest or optional ML packages."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from importlib.metadata import distributions
from pathlib import Path

from flakydetector.analyzer.ast_analyzer import EXCLUDE

PROVENANCE_VERSION = 3


def source_fingerprint(root: Path) -> str:
    digest = hashlib.sha256(b"flaky-source-v3\0")
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE and not Path(current, d).is_symlink())
        for name in sorted(files):
            path = Path(current, name)
            if not path.is_symlink() and (
                path.suffix == ".py"
                or name
                in {
                    "pyproject.toml",
                    "uv.lock",
                    "poetry.lock",
                    "pytest.ini",
                    "tox.ini",
                    "setup.cfg",
                }
            ):
                digest.update(path.relative_to(root).as_posix().encode() + b"\0")
                content = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(65536), b""):
                        content.update(block)
                digest.update(content.digest())
    return digest.hexdigest()


def environment_fingerprint() -> str:
    snapshot = [
        sys.version,
        platform.platform(),
        sorted((d.metadata.get("Name", ""), d.version) for d in distributions()),
    ]
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
