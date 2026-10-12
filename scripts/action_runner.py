"""Trusted action driver: parse target source, never install/import its application."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from flakydetector.security.privacy import safe_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", default=".")
    parser.add_argument("--base", default="")
    parser.add_argument(
        "--threshold",
        choices=["none", "low", "medium", "high", "critical"],
        default="high",
    )
    args = parser.parse_args()
    if os.getenv("GITHUB_EVENT_NAME") == "pull_request_target":
        raise SystemExit(
            "Refusing privileged pull_request_target; use pull_request with a pinned trusted action",
        )
    if os.getenv("GITHUB_EVENT_NAME") == "pull_request" and args.base:
        event_path = Path(os.environ["GITHUB_EVENT_PATH"])
        if event_path.stat().st_size > 2000000:
            raise SystemExit("Event context exceeds budget")
        event = json.loads(event_path.read_text())
        if args.base != event.get("pull_request", {}).get("base", {}).get("sha"):
            raise SystemExit("PR baseline must be its trusted GitHub base SHA")
    root = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    scope = "." if args.scope == "." else safe_path(args.scope)
    if args.base and (not re.fullmatch("[a-f0-9]{40,64}", args.base)):
        raise SystemExit("Base must be an immutable commit SHA")
    out = Path(tempfile.mkdtemp(prefix="fd-action-", dir=os.environ.get("RUNNER_TEMP")))
    sarif = out / "results.sarif"
    summary = out / "summary.md"
    baseline = out / "baseline.json"
    command = [
        sys.executable,
        "-I",
        "-m",
        "flakydetector.cli",
        scope,
        "--project-root",
        str(root),
        "--format",
        "sarif",
        "--output",
        str(sarif),
        "--summary",
        str(summary),
        "--github-annotations",
        "--isolated",
        "--fail-on",
        args.threshold,
    ]
    code = 2
    if args.base:
        base_root = out / "base"
        base_root.mkdir()
        # Read Git blobs, not a checkout with filters/hooks. Bound count and bytes.
        raw = subprocess.run(
            ["git", "ls-tree", "-rz", args.base, "--", scope],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
        total = count = 0
        for entry in raw.split(b"\x00"):
            if not entry:
                continue
            meta, name = entry.split(b"\t", 1)
            mode, kind, blob = meta.decode().split()
            if mode not in {"100644", "100755"}:
                continue
            p = Path(name.decode())
            if not (
                p.name == "conftest.py"
                or (
                    p.suffix == ".py"
                    and (p.name.startswith("test_") or p.name.endswith("_test.py"))
                )
            ):
                continue
            path = safe_path(name.decode())
            size = int(
                subprocess.run(
                    ["git", "cat-file", "-s", blob],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout,
            )
            if size > 1000000 or count >= 500 or total + size > 20000000:
                raise SystemExit("Base exceeds analysis budget")
            content = subprocess.run(
                ["git", "cat-file", "blob", blob],
                cwd=root,
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout
            count += 1
            total += len(content)
            if count > 500 or total > 20000000 or len(content) > 1000000:
                raise SystemExit("Base exceeds analysis budget")
            target = base_root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-m",
                "flakydetector.cli",
                scope,
                "--project-root",
                str(base_root),
                "--fail-on",
                "none",
                "--isolated",
                "--write-baseline",
                str(baseline),
                "--revision",
                args.base,
                "--accepted-by",
                "trusted-base-comparison",
            ],
            cwd=base_root,
            check=False,
        )
        if result.returncode == 0:
            command += ["--baseline", str(baseline), "--baseline-revision", args.base, "--new-only"]
        else:
            with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
                stream.write("exit_code=2\n")
            print("Base analysis incomplete: no debt policy was silently accepted")
            return
    result = subprocess.run(command, cwd=root, check=False)
    code = result.returncode if result.returncode in {0, 1, 2} else 2
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write(f"exit_code={code}\n")
        if sarif.exists():
            stream.write(f"sarif={sarif}\n")
    if summary.exists():
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(summary.read_text())


if __name__ == "__main__":
    main()
