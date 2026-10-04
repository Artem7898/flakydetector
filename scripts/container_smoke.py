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


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 600,
    log_path: Path | None = None,
) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    output = result.stdout + result.stderr
    if log_path is not None:
        log_path.write_text(output, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}\n{result.stderr}"
        )
    return output


def wait_for_ready(
    url: str,
    container_id: str,
    *,
    timeout: float = 60.0,
    interval: float = 1.0,
) -> None:
    """Wait for HTTP 200 with a deadline; a transient reset is not a startup failure.

    A stopped container, invalid HTTP response, or expired deadline still fails.
    Retry only during readiness, never the assertions on assets or analysis.
    """
    if timeout <= 0 or interval <= 0:
        raise ValueError("Readiness timeout and interval must be positive")
    deadline = time.monotonic() + timeout
    last_error = "no readiness response"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"Container did not become ready within {timeout:g}s: {last_error}")
        state = json.loads(
            run(
                ["docker", "inspect", "--format", "{{json .State}}", container_id],
                timeout=min(10.0, remaining),
            )
        )
        if not isinstance(state, dict) or state.get("Running") is not True:
            raise RuntimeError(f"Container exited before readiness: {state}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"Container did not become ready within {timeout:g}s: {last_error}")
        try:
            with urllib.request.urlopen(url, timeout=min(3.0, remaining)) as response:
                if response.status != 200:
                    raise RuntimeError(f"Readiness endpoint returned HTTP {response.status}")
            return
        except urllib.error.HTTPError as exc:
            # Startup/proxy unavailability is transient; wrong routes/auth are not.
            exc.close()
            if exc.code not in {502, 503, 504}:
                raise RuntimeError(f"Readiness endpoint returned HTTP {exc.code}") from exc
            last_error = f"HTTP {exc.code}: {exc.reason}"
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval, remaining))


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
            report["stage"] = "build"
            run(
                ["docker", "build", "--tag", tag, "."],
                cwd=root,
                timeout=1200,
                log_path=args.report.with_suffix(".build.log"),
            )
            built = True
            report["stage"] = "start"
            # Preserve a failed container until its diagnostics have been captured.
            # The finally block removes only this smoke run's own container.
            container_id = run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--read-only",
                    "--tmpfs",
                    "/tmp",
                    "--publish",
                    "127.0.0.1::8000",
                    tag,
                ]
            ).strip()
            port = run(["docker", "port", container_id, "8000/tcp"]).strip().rsplit(":", 1)[-1]
            base = f"http://127.0.0.1:{port}"
            report["stage"] = "readiness"
            wait_for_ready(base + "/ready", container_id)
            report["stage"] = "frontend"
            with urllib.request.urlopen(base + "/", timeout=5) as response:
                html = response.read().decode()
                assert "text/html" in response.headers["content-type"]
            assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
            assert assets, "Built frontend assets are missing"
            for asset in assets:
                with urllib.request.urlopen(base + asset, timeout=5) as response:
                    assert response.status == 200 and len(response.read()) > 0
            report["stage"] = "analysis"
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
            report.update(
                status="passed",
                stage="complete",
                image_id=run(["docker", "image", "inspect", "--format", "{{.Id}}", tag]).strip(),
                ready=True,
                html=True,
                assets=True,
                analysis=True,
            )
            exit_code = 0
    except (OSError, ValueError, RuntimeError, AssertionError, subprocess.SubprocessError) as exc:
        report["reason"] = str(exc)
        exit_code = 2 if report["status"] == "blocked" else 1
        if container_id:
            logs = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True)
            args.report.with_suffix(".container.log").write_text(logs.stdout + logs.stderr)
    finally:
        if container_id:
            subprocess.run(
                ["docker", "rm", "--force", container_id], capture_output=True, check=False
            )
        if built:
            subprocess.run(["docker", "image", "rm", tag], capture_output=True, check=False)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
