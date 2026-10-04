"""Run real gates against an extracted final ZIP; emit evidence beside (not inside) it.

No source checkout imports are used. Requires uv, Node/npm and optionally Docker.
A nonzero/blocked command fails the verification; it never becomes an invented pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from check_release import MANIFEST, read_release


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", default="3.12")
    parser.add_argument("--without-docker", action="store_true")
    args = parser.parse_args()
    archive = args.archive.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    files = read_release(archive)
    report: dict[str, object] = {
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256(files[MANIFEST]).hexdigest(),
        "checks": [],
    }
    checks: list[dict[str, object]] = []
    report["checks"] = checks
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "VIRTUAL_ENV", "PYTEST_ADDOPTS"}
    }
    env["REQUIRE_RENDER_TESTS"] = "1"
    failed = False
    with tempfile.TemporaryDirectory(prefix="flaky-final-artifact-") as folder:
        root = Path(folder)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        commands = [
            (
                "locked-install",
                [
                    "uv",
                    "sync",
                    "--locked",
                    "--python",
                    args.python,
                    "--extra",
                    "api",
                    "--extra",
                    "dev",
                    "--extra",
                    "ml",
                    "--extra",
                    "github",
                ],
                root,
            ),
            ("ruff", ["uv", "run", "--frozen", "ruff", "check", "."], root),
            ("format", ["uv", "run", "--frozen", "ruff", "format", "--check", "."], root),
            ("pyright", ["uv", "run", "--frozen", "pyright"], root),
            ("pytest", ["uv", "run", "--frozen", "python", "-m", "pytest", "-q"], root),
            ("build", ["uv", "build"], root),
            (
                "installed-wheel",
                ["uv", "run", "--frozen", "python", "scripts/installed_wheel_smoke.py"],
                root,
            ),
            ("frontend-install", ["npm", "ci", "--ignore-scripts"], root / "dashboard_frontend"),
            ("frontend-tests", ["npm", "test"], root / "dashboard_frontend"),
            ("frontend-build", ["npm", "run", "build"], root / "dashboard_frontend"),
        ]
        if not args.without_docker:
            commands.append(
                (
                    "container",
                    [
                        sys.executable,
                        str(root / "scripts/container_smoke.py"),
                        str(archive),
                        "--report",
                        str(output / "container.json"),
                    ],
                    root,
                )
            )
        else:
            checks.append({"name": "container", "status": "not_run", "reason": "--without-docker"})
        for name, command, cwd in commands:
            print(f"\n=== {name}: {' '.join(command)} ===", flush=True)
            if shutil.which(command[0]) is None:
                checks.append(
                    {"name": name, "status": "blocked", "reason": f"{command[0]} unavailable"}
                )
                print(f"BLOCKED: {command[0]} unavailable", flush=True)
                failed = True
                continue
            try:
                process = subprocess.run(
                    command, cwd=cwd, env=env, text=True, capture_output=True, timeout=1200
                )
                (output / f"{name}.txt").write_text(process.stdout + process.stderr)
                print(process.stdout + process.stderr, end="", flush=True)
                print(f"\n=== {name}: exit {process.returncode} ===", flush=True)
                checks.append(
                    {
                        "name": name,
                        "status": "passed" if process.returncode == 0 else "failed",
                        "returncode": process.returncode,
                    }
                )
                failed |= process.returncode != 0
            except subprocess.TimeoutExpired:
                checks.append({"name": name, "status": "failed", "reason": "timeout"})
                print(f"FAILED: {name} exceeded its timeout", flush=True)
                failed = True
        changed = [
            name
            for name, content in files.items()
            if not (root / name).is_file() or (root / name).read_bytes() != content
        ]
        checks.append(
            {
                "name": "source-integrity",
                "status": "failed" if changed else "passed",
                "changed": changed,
            }
        )
        failed |= bool(changed)
    report["status"] = "failed" if failed else ("partial" if args.without_docker else "passed")
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
