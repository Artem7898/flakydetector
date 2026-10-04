"""Run with an installed wheel from outside the repository; no source imports allowed."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from importlib.metadata import version
from pathlib import Path

from fastapi.testclient import TestClient

import flakydetector
from flakydetector.dashboard.main import create_app

SOURCE = "import time\ndef test_wait():\n    time.sleep(1)\ndef test_clean():\n    assert 1 == 1\n"


def main() -> None:
    installed = Path(flakydetector.__file__).resolve()
    assert "site-packages" in installed.parts, installed
    assert importlib.util.find_spec("catboost") is None, "Smoke environment must omit optional ML"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "test_corpus.py"
        path.write_text(SOURCE, encoding="utf-8")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(path.name, SOURCE)

        def normalize(payload: dict[str, object]) -> dict[str, object]:
            return {k: v for k, v in payload.items() if k != "analysis_id"}

        run = subprocess.run(
            [
                str(Path(sys.executable).with_name("flakydetector")),
                str(path),
                "--format",
                "json",
                "--fail-on",
                "none",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        expected = normalize(json.loads(run.stdout))
        with TestClient(create_app()) as client:
            assert client.get("/ready").status_code == 200
            responses = [
                client.post(
                    "/api/v1/analyze", json={"file_content": SOURCE, "file_path": path.name}
                ),
                client.post("/api/v1/analyze/file", files={"file": (path.name, SOURCE)}),
                client.post(
                    "/api/v1/analyze/directory", files={"file": ("corpus.zip", buffer.getvalue())}
                ),
            ]
            for response in responses:
                assert response.status_code == 200, response.text
                assert normalize(response.json()) == expected
            assert (
                client.post("/api/v1/analyze", json={"file_content": "def broken(:"}).status_code
                == 422
            )
        path.write_text("def test_ok(): pass\n", encoding="utf-8")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(path),
                "--flaky-trail",
                "--flaky-trail-db",
                str(root / "trail.db"),
                "-q",
            ],
            cwd=root,
            check=True,
            timeout=30,
        )
    print(
        json.dumps(
            {
                "wheel_version": version("flakydetector"),
                "installed_from_site_packages": True,
                "optional_ml_absent": True,
                "cli_json_file_zip_parity": True,
                "pytest_entrypoint": True,
            }
        )
    )


if __name__ == "__main__":
    main()
