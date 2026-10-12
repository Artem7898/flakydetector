"""Real multipart handlers/child processes for the upload and product-number correction."""

from __future__ import annotations

import io
import json
import tomllib
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flakydetector import __version__
from flakydetector.application import AnalyzeService
from flakydetector.classifier.schema import FEATURE_SCHEMA_VERSION
from flakydetector.dashboard.main import create_app
from flakydetector.reporting.sarif import to_sarif
from flakydetector.utils.config import Settings

ROOT = Path(__file__).resolve().parents[2]
SOURCE = b"def test_selected_upload():\n    assert True\n"


def zip_source() -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("tests/test_selected.py", SOURCE)
    return data.getvalue()


@pytest.fixture
def client():
    with TestClient(create_app(), client=("127.0.0.1", 12000), base_url="http://127.0.0.1") as api:
        yield api


@pytest.mark.parametrize("name", ["test_selected.py", "TEST_SELECTED.PY", "проверка.py"])
@pytest.mark.parametrize("content_type", ["text/plain", "application/octet-stream"])
def test_real_python_upload_does_not_depend_on_desktop_mime(client, name, content_type):
    response = client.post("/api/v1/analyze/file", files={"file": (name, SOURCE, content_type)})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["test_candidates"] == 1
    assert any(item["test_name"] == "test_selected_upload" for item in result["results"])
    assert result["source_snapshots"] == []
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("name", ["tests.zip", "TESTS.ZIP", "Тесты.ZiP"])
def test_real_archive_upload_retains_zip_validation(client, name):
    response = client.post(
        "/api/v1/analyze/directory",
        files={"file": (name, zip_source(), "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["test_candidates"] == 1
    assert response.json()["source_snapshots"] == []


@pytest.mark.parametrize("name", ["test.py.txt", ".env", "events.jsonl", "test.exe"])
def test_unfiltered_picker_does_not_weaken_server_type_checks(client, name):
    response = client.post("/api/v1/analyze/file", files={"file": (name, SOURCE, "text/x-python")})
    assert response.status_code == 422
    assert "test_selected_upload" not in response.text


def test_syntax_error_is_structured_and_does_not_echo_uploaded_source(client):
    response = client.post(
        "/api/v1/analyze/file",
        files={"file": ("broken.py", b'SECRET="CANARY_UPLOAD"\ndef broken(:', "text/plain")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["schema_version"] == "3.0.0"
    assert "CANARY_UPLOAD" not in response.text


def test_product_metadata_health_openapi_and_sarif_agree(client):
    assert __version__ == "0.2.2"
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    packages = [p for p in lock["package"] if p["name"] == "flakydetector"]
    frontend = json.loads((ROOT / "dashboard_frontend/package.json").read_text())
    frontend_lock = json.loads((ROOT / "dashboard_frontend/package-lock.json").read_text())
    assert metadata["project"]["version"] == frontend["version"] == __version__
    assert len(packages) == 1 and packages[0]["version"] == __version__
    assert frontend_lock["version"] == frontend_lock["packages"][""]["version"] == __version__
    assert client.get("/health").json()["version"] == __version__
    assert client.get("/api/openapi.json").json()["info"]["version"] == __version__
    result = AnalyzeService(Settings()).analyze({"test_x.py": SOURCE.decode()})
    sarif = to_sarif(result)
    assert sarif["runs"][0]["tool"]["driver"]["version"] == __version__
    # Product numbering must not roll back incompatible wire/model/storage contracts.
    assert result.schema_version == FEATURE_SCHEMA_VERSION == "3.0.0"
    assert sarif["version"] == "2.1.0"
