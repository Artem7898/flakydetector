"""Same corpus through JSON/file/ZIP/installed CLI; explicit negative results."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient

from flakydetector.application import AnalyzeService
from flakydetector.dashboard.main import create_app
from flakydetector.input import InputError, zip_bundle
from flakydetector.utils.config import Settings

CORPUS = """import pytest
import time as clock
import requests
@pytest.fixture(scope="session")
def shared():
    return {}
def test_network(shared):
    requests.get("https://example.test")
async def test_clock():
    clock.sleep(1)
def test_clean():
    assert 1 == 1
"""


def archive(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buffer.getvalue()


def semantic(value):
    return {k: v for k, v in value.items() if k not in {"analysis_id", "timestamp"}}


@pytest.fixture
def client():
    with TestClient(create_app()) as value:
        yield value


def test_four_adapters_same_corpus(client, tmp_path):
    code = client.post(
        "/api/v1/analyze", json={"file_content": CORPUS, "file_path": "test_corpus.py"}
    ).json()
    uploaded = client.post(
        "/api/v1/analyze/file", files={"file": ("test_corpus.py", CORPUS)}
    ).json()
    zipped = client.post(
        "/api/v1/analyze/directory",
        files={"file": ("corpus.zip", archive({"test_corpus.py": CORPUS}))},
    ).json()
    path = tmp_path / "test_corpus.py"
    path.write_text(CORPUS)
    environment = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "flakydetector.cli",
            str(path),
            "--format",
            "json",
            "--fail-on",
            "none",
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr
    assert (
        semantic(code) == semantic(uploaded) == semantic(zipped) == semantic(json.loads(run.stdout))
    )
    assert len(code["results"]) == 3
    assert code["results"][0]["risk_score"] > 0
    assert code["results"][2]["verdict"] == "no_known_risk"
    assert code["results"][0]["calibrated_probability"] is None


@pytest.mark.parametrize("source", ["def bad(:", ""])
def test_invalid_source_not_success(client, source):
    response = client.post("/api/v1/analyze", json={"file_content": source})
    assert response.status_code == 422


def test_model_degraded_does_not_erase_rules(client):
    response = client.post(
        "/api/v1/analyze", json={"file_content": CORPUS, "use_ml_classifier": True}
    ).json()
    assert response["status"] == "partial"
    assert response["degraded_reason"]
    assert response["results"][0]["backend_used"] == "rules"
    assert response["results"][0]["risk_score"] > 0


def test_missing_model_readiness(tmp_path):
    with TestClient(create_app(Settings(model_path=tmp_path / "missing.cbm"))) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503


def test_unique_analysis_identity_and_locations(client):
    first = client.post("/api/v1/analyze", json={"file_content": CORPUS}).json()
    second = client.post("/api/v1/analyze", json={"file_content": CORPUS}).json()
    assert first["analysis_id"] != second["analysis_id"]
    p = first["results"][0]["patterns"][0]
    assert p["location"]["line_start"] > 0 and p["location"]["function_name"]
    assert p["confidence"] > 0


@pytest.mark.parametrize(
    "name,raw,expected",
    [
        ("empty.py", b"", 422),
        ("bad.py", b"\xff", 422),
        ("data.zip", b"broken", 422),
        ("empty.zip", archive({"readme.txt": "hello"}), 422),
        ("evil.zip", archive({"../test_escape.py": "pass"}), 422),
    ],
)
def test_input_error_routes(client, name, raw, expected):
    endpoint = "directory" if name.endswith(".zip") else "file"
    assert (
        client.post("/api/v1/analyze/" + endpoint, files={"file": (name, raw)}).status_code
        == expected
    )


def test_zip_bounded_and_no_path_write(tmp_path):
    with pytest.raises(InputError):
        zip_bundle(archive({"../test_escape.py": "pass"}), Settings())
    assert not (tmp_path / "test_escape.py").exists()
    with pytest.raises(InputError, match="limit"):
        zip_bundle(archive({"test_a.py": "x" * 100}), Settings(max_file_bytes=20))


def test_optional_routes_fail_visibly(client):
    assert client.get("/api/v1/search_similar", params={"query": "race"}).status_code == 503
    assert client.get("/api/v1/features/importance").status_code == 503
    assert client.get("/api/v1/stats/org/repo").status_code == 501


def test_auth_gate():
    with TestClient(create_app(Settings(api_token="unit-test-only"))) as client:
        assert client.post("/api/v1/analyze", json={"file_content": CORPUS}).status_code == 401
        assert (
            client.post(
                "/api/v1/analyze",
                json={"file_content": CORPUS},
                headers={"Authorization": "Bearer unit-test-only"},
            ).status_code
            == 200
        )


def test_empty_scan_and_fixture_only_request():
    assert AnalyzeService().analyze({}).status == "error"

    class Model:
        def __init__(self):
            self.received = []

        def predict_single(self, features):
            self.received.append(features)
            return True, 0.8

    model = Model()
    response = AnalyzeService(classifier=model).analyze(
        {
            "test_a.py": 'import pytest\n@pytest.fixture(scope="session")\ndef state():\n    return {}\ndef test_a(state): pass\n'
        },
        use_ml=True,
    )
    assert len(model.received) == 1 and model.received[0][-1] == 1
    assert response.results[0].backend_used == "ml"


def test_cli_exit_codes(tmp_path):
    path = tmp_path / "test_a.py"
    for source, expected in [
        ("def test_a(): pass", 0),
        ('import requests\ndef test_a(): requests.get("url")', 1),
        ("def bad(:", 2),
    ]:
        path.write_text(source)
        result = subprocess.run(
            [sys.executable, "-m", "flakydetector.cli", str(path)],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == expected, (result.stdout, result.stderr)


def test_testless_file_is_not_empty_success(client):
    response = client.post(
        "/api/v1/analyze", json={"file_content": "import os\n", "file_path": "test_empty.py"}
    )
    assert response.status_code == 422
    assert any(d["code"] == "no_tests" for d in response.json()["detail"]["diagnostics"])


def test_body_limit_is_413():
    with TestClient(create_app(Settings(max_archive_bytes=32))) as client:
        response = client.post(
            "/api/v1/analyze", content=b"x" * 70000, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 413
