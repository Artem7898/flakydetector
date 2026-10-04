"""Build and smoke-test a container from a validated ZIP, never from the checkout.

Requires Docker. A missing daemon/tool is BLOCKED, not a passing smoke result.
Only the temporary image/container created by this script are removed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from check_release import read_release


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 600) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}\n{result.stderr}")
    return result.stdout + result.stderr


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report: dict[str, object] = {
        "archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        "status": "blocked",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    tag = f"flakydetector:smoke-{uuid4().hex[:12]}"
    container_id = ""
    built = False
    exit_code = 2
    try:
        files = read_release(args.archive)
        if shutil.which("docker") is None:
            raise FileNotFoundError("Docker CLI is unavailable; container smoke was not executed")
        run(["docker", "info"], timeout=30)
        report["status"] = "failed"
        with tempfile.TemporaryDirectory(prefix="flaky-container-") as folder:
            root = Path(folder)
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            build_log = run(["docker", "build", "--tag", tag, "."], cwd=root, timeout=1200)
            args.report.with_suffix(".build.log").write_text(build_log)
            built = True
            container_id = run([
                "docker", "run", "--detach", "--rm", "--read-only", "--tmpfs", "/tmp",
                "--publish", "127.0.0.1::8000", tag,
            ]).strip()
            port = run(["docker", "port", container_id, "8000/tcp"]).strip().rsplit(":", 1)[-1]
            base = f"http://127.0.0.1:{port}"
            for attempt in range(60):
                try:
                    with urllib.request.urlopen(base + "/ready", timeout=3) as response:
                        assert response.status == 200
                    break
                except (urllib.error.URLError, TimeoutError):
                    if attempt == 59:
                        raise RuntimeError("Container did not become ready") from None
                    time.sleep(1)
            with urllib.request.urlopen(base + "/", timeout=5) as response:
                html = response.read().decode()
                assert "text/html" in response.headers["content-type"]
            assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
            assert assets, "Built frontend assets are missing"
            for asset in assets:
                with urllib.request.urlopen(base + asset, timeout=5) as response:
                    assert response.status == 200 and len(response.read()) > 0
            source = "import time\ndef test_wait():\n    time.sleep(1)\n"
            request = urllib.request.Request(
                base + "/api/v1/analyze",
                data=json.dumps({"file_content": source, "file_path": "test_smoke.py"}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.load(response)
            assert payload["schema_version"] == "2.1.0" and payload["test_candidates"] == 1
            assert payload["results"][0]["verdict"] == "risk_detected"
            assert payload["source_snapshots"][0]["content"] == source
            report.update(status="passed", image_id=run(["docker", "image", "inspect", "--format", "{{.Id}}", tag]).strip(),
                          ready=True, html=True, assets=True, analysis=True)
            exit_code = 0
    except (OSError, ValueError, RuntimeError, AssertionError, subprocess.SubprocessError) as exc:
        report["reason"] = str(exc)
        exit_code = 2 if report["status"] == "blocked" else 1
        if container_id:
            logs = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True)
            args.report.with_suffix(".container.log").write_text(logs.stdout + logs.stderr)
    finally:
        if container_id:
            subprocess.run(["docker", "rm", "--force", container_id], capture_output=True, check=False)
        if built:
            subprocess.run(["docker", "image", "rm", tag], capture_output=True, check=False)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
