"""Real child processes and ASGI requests; no model/network side effects or mock executor."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flakydetector.dashboard.main import create_app
from flakydetector.security.auth import SCOPES
from flakydetector.utils.config import Settings
from flakydetector.workers.supervisor import (
    ProcessSupervisor,
    WorkerBusy,
    WorkerFailure,
    WorkerTimeout,
)
from tests.unit.test_product_core import events

SOURCE = 'import time\nsecret="CANARY_SECRET"\ndef test_x():\n    time.sleep(1)\n'


def shared(tmp_path, scopes, workspace="local"):
    token = "example-access-token-for-tests-only"
    credentials = tmp_path / "credentials.json"
    credentials.write_text(
        json.dumps(
            [
                {
                    "subject": "reviewer",
                    "sha256": hashlib.sha256(token.encode()).hexdigest(),
                    "workspaces": [workspace],
                    "scopes": list(scopes),
                },
            ],
        ),
    )
    settings = Settings(
        profile="shared",
        allow_remote=True,
        credentials_file=credentials,
        source_mode="redacted",
        evidence_db=tmp_path / "ledger.db",
    )
    return (create_app(settings), {"Authorization": f"Bearer {token}"})


@pytest.mark.parametrize(
    "code",
    [SOURCE, 'secret="CANARY_SECRET"\ndef broken(:', "", {"secret": "CANARY_SECRET"}],
)
def test_source_absent_from_success_and_errors_by_default(code):
    with TestClient(
        create_app(), client=("127.0.0.1", 1234), base_url="http://127.0.0.1"
    ) as client:
        response = client.post("/api/v1/analyze", json={"file_content": code})
    assert response.status_code in {200, 422}
    assert "CANARY_SECRET" not in response.text
    assert response.headers["cache-control"] == "no-store"
    if response.status_code == 200:
        assert response.json()["source_snapshots"] == []
        assert response.json()["source_access"] == "disabled"


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-Forwarded-For": "127.0.0.1"}, {"Forwarded": "for=127.0.0.1"}],
)
def test_direct_uvicorn_remote_cannot_bypass_local_profile(headers):
    with TestClient(
        create_app(), client=("203.0.113.40", 1234), base_url="http://127.0.0.1"
    ) as client:
        response = client.post("/api/v1/analyze", json={"file_content": SOURCE}, headers=headers)
    assert response.status_code == 403 and "CANARY_SECRET" not in response.text


def test_scopes_checked_before_source_and_export(tmp_path):
    app, headers = shared(tmp_path, {"analyze", "findings:read"})
    with TestClient(app, client=("203.0.113.40", 1234), base_url="http://127.0.0.1") as client:
        assert client.post("/api/v1/analyze", json={"file_content": SOURCE}).status_code == 401
        response = client.post(
            "/api/v1/analyze?include_source=true",
            json={"file_content": SOURCE},
            headers=headers,
        )
        payload = response.json()
        assert (
            response.status_code == 200
            and payload["source_access"] == "denied"
            and (not payload["source_snapshots"])
        )
        assert (
            client.post(
                "/api/v1/analyze?workspace=other", json={"file_content": SOURCE}, headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post("/api/v1/export", json={"analysis": payload}, headers=headers).status_code
            == 403
        )
        assert client.get("/api/v1/events?repo=a/b", headers=headers).status_code == 403


def test_source_export_requires_confirmation_and_expiry(tmp_path):
    app, headers = shared(tmp_path, SCOPES)
    with TestClient(app, client=("203.0.113.40", 1234), base_url="http://127.0.0.1") as client:
        result = client.post(
            "/api/v1/analyze?include_source=true",
            json={"file_content": SOURCE},
            headers=headers,
        )
        assert result.status_code == 200
        payload = result.json()
        assert payload["source_access"] == "redacted"
        assert payload["source_snapshots"] and "CANARY_SECRET" not in result.text
        assert (
            payload["source_digests"]["test_sample.py"]
            == hashlib.sha256(SOURCE.encode()).hexdigest()
        )
        no_confirm = client.post(
            "/api/v1/export",
            json={"analysis": payload, "include_source": True},
            headers=headers,
        )
        assert no_confirm.status_code == 403
        ordinary = client.post("/api/v1/export", json={"analysis": payload}, headers=headers)
        assert ordinary.status_code == 200 and ordinary.json()["classification"] == "source-free"
        assert ordinary.json()["analysis"]["source_snapshots"] == []
        sarif = client.post(
            "/api/v1/export", json={"analysis": payload, "format": "sarif"}, headers=headers
        )
        assert sarif.status_code == 200 and sarif.json()["version"] == "2.1.0"
        explicit = client.post(
            "/api/v1/export",
            json={"analysis": payload, "include_source": True, "confirm_source": True},
            headers=headers,
        )
        assert (
            explicit.status_code == 200
            and explicit.json()["classification"] == "source-bearing-redacted"
        )
        payload["source_expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        assert (
            client.post(
                "/api/v1/export",
                json={"analysis": payload, "include_source": True, "confirm_source": True},
                headers=headers,
            ).status_code
            == 410
        )


def test_runtime_ingest_idempotency_derived_monitors_and_acl(tmp_path):
    app, headers = shared(tmp_path, SCOPES)
    rows = events("failed") + events(
        "passed", attempt=2, when=datetime(2026, 10, 11, 0, 1, tzinfo=UTC)
    )
    payload = {"events": [e.model_dump(mode="json") for e in rows]}
    with TestClient(app, client=("203.0.113.40", 1234), base_url="http://127.0.0.1") as client:
        added = client.post("/api/v1/events", json=payload, headers=headers)
        assert added.status_code == 200 and added.json() == {"added": 6, "duplicates": 0}
        assert client.post("/api/v1/events", json=payload, headers=headers).json() == {
            "added": 0,
            "duplicates": 6,
        }
        monitors = client.get("/api/v1/monitors?repo=a/b", headers=headers)
        assert monitors.status_code == 200
        assert any(
            (
                o["monitor"] == "pass_on_retry" and o["status"] == "detected"
                for o in monitors.json()["observations"]
            ),
        )
        assert (
            client.get("/api/v1/stats/a/b", headers=headers).json()["metrics"][
                "pass_on_retry_count"
            ]
            == 1
        )
        tamper = json.loads(json.dumps(payload))
        tamper["events"][0]["duration"] = 10
        assert client.post("/api/v1/events", json=tamper, headers=headers).status_code == 409
        tamper = json.loads(json.dumps(payload))
        tamper["events"][0]["collector"] = "external"
        assert client.post("/api/v1/events", json=tamper, headers=headers).status_code == 403
        assert (
            client.get("/api/v1/monitors?repo=a/b&workspace=other", headers=headers).status_code
            == 403
        )


def test_quarantine_owner_is_authenticated_and_versions_are_concurrent(tmp_path):
    app, headers = shared(tmp_path, SCOPES)
    entry = {
        "repo": "a/b",
        "nodeid": "test_x.py::test_x",
        "source_hash": "a" * 64,
        "owner": "team",
        "issue": "issue:5",
        "reason": "Investigating cleanup before release",
        "ttl_days": 7,
    }
    with TestClient(app, client=("203.0.113.40", 1234), base_url="http://127.0.0.1") as client:
        created = client.post("/api/v1/quarantine", json=entry, headers=headers)
        assert created.status_code == 200
        record = created.json()
        assert record["approved_by"] == "reviewer"
        assert (
            client.post(
                "/api/v1/quarantine", json={**entry, "approved_by": "forged"}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.get("/api/v1/quarantine?repo=a/b", headers=headers).json()["entries"][0]["id"]
            == record["id"]
        )


@pytest.mark.asyncio
async def test_real_worker_timeout_kills_descendants_and_releases_slot(tmp_path):
    pidfile = tmp_path / "pid"
    worker = ProcessSupervisor(Settings(timeout_seconds=0.2))
    command = [
        sys.executable,
        "-c",
        f'import os,time; child=os.fork(); open({str(pidfile)!r}+str(child==0),"w").write(str(os.getpid())); time.sleep(5)',
    ]
    with pytest.raises(WorkerTimeout):
        await worker.execute(command, b"")
    assert worker.active == 0 and worker.pids == set()
    for f in tmp_path.glob("pid*"):
        process_file = Path("/proc") / f.read_text() / "stat"
        if process_file.exists():
            assert process_file.read_text().split()[2] == "Z"
    assert await worker.execute([sys.executable, "-c", 'print("ok")'], b"") == b"ok\n"


@pytest.mark.asyncio
async def test_real_worker_cancellation_and_capacity(tmp_path):
    worker = ProcessSupervisor(Settings(timeout_seconds=5))
    command = [sys.executable, "-c", "import time;time.sleep(5)"]
    one = asyncio.create_task(worker.execute(command, b""))
    two = asyncio.create_task(worker.execute(command, b""))
    for _ in range(200):
        if len(worker.pids) == 2:
            break
        await asyncio.sleep(0.005)
    assert worker.active == 2
    with pytest.raises(WorkerBusy):
        await worker.execute(command, b"")
    one.cancel()
    two.cancel()
    await asyncio.gather(one, two, return_exceptions=True)
    assert worker.active == 0 and worker.pids == set()


@pytest.mark.asyncio
async def test_worker_never_inherits_credentials(monkeypatch):
    monkeypatch.setenv("FLAKY_API_TOKEN", "CANARY_SECRET")
    monkeypatch.setenv("OPENAI_API_KEY", "CANARY_SECRET")
    monkeypatch.setenv("PYTHONPATH", "/hostile")
    worker = ProcessSupervisor(Settings())
    output = await worker.execute(
        [sys.executable, "-c", "import os,json;print(json.dumps(dict(os.environ)))"], b""
    )
    assert b"CANARY_SECRET" not in output and b"PYTHONPATH" not in output


@pytest.mark.asyncio
async def test_actual_worker_does_not_execute_submitted_python(tmp_path):
    marker = tmp_path / "should-not-exist"
    worker = ProcessSupervisor(Settings())
    result = await worker.run(
        {
            "operation": "analyze",
            "sources": {
                "test_a.py": f'open({str(marker)!r},"w").write("executed")\ndef test_x(): pass'
            },
            "use_ml": False,
        },
    )
    assert result["test_candidates"] == 1 and (not marker.exists())


@pytest.mark.asyncio
async def test_actual_worker_node_limit_and_malformed_input():
    worker = ProcessSupervisor(Settings(max_ast_nodes=10))
    result = await worker.run(
        {
            "operation": "analyze",
            "sources": {
                "test_x.py": "def test_x():\n" + "".join(f"    v{i}={i}\n" for i in range(20))
            },
        },
    )
    assert result["status"] == "error"
    with pytest.raises(WorkerFailure):
        await worker.run({"operation": "not_supported"})


def test_source_grant_cannot_be_extended_or_modified(tmp_path):
    app, headers = shared(tmp_path, SCOPES)
    with TestClient(app, client=("203.0.113.40", 1234), base_url="http://127.0.0.1") as client:
        original = client.post(
            "/api/v1/analyze?include_source=true",
            json={"file_content": SOURCE},
            headers=headers,
        ).json()
        assert original["source_grant"]
        changed = {
            **original,
            "source_expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        }
        assert (
            client.post(
                "/api/v1/export",
                json={"analysis": changed, "include_source": True, "confirm_source": True},
                headers=headers,
            ).status_code
            == 403
        )
        changed = json.loads(json.dumps(original))
        changed["source_snapshots"][0]["content"] = "arbitrary replacement source"
        assert (
            client.post(
                "/api/v1/export",
                json={"analysis": changed, "include_source": True, "confirm_source": True},
                headers=headers,
            ).status_code
            == 403
        )
        exported = client.post(
            "/api/v1/export",
            json={"analysis": original, "include_source": True, "confirm_source": True},
            headers=headers,
        ).json()["analysis"]
        assert exported["source_expires_at"] == original["source_expires_at"]
        # An export is not a renewal capability.
        assert exported["source_grant"] is None


def test_local_host_and_origin_rebinding_rejected():
    with TestClient(
        create_app(), client=("127.0.0.1", 1234), base_url="http://127.0.0.1"
    ) as client:
        assert (
            client.post(
                "/api/v1/analyze",
                headers={"host": "attacker.invalid", "origin": "http://attacker.invalid"},
                json={"file_content": SOURCE},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/v1/analyze",
                headers={"origin": "https://attacker.invalid"},
                json={"file_content": SOURCE},
            ).status_code
            == 403
        )
        assert client.get("/ready", headers={"host": "localhost:8001"}).status_code == 200


def test_quarantine_renew_revoke_has_optimistic_version_and_audit(tmp_path):
    app, headers = shared(tmp_path, SCOPES)
    with TestClient(app, client=("203.0.113.40", 1234), base_url="http://127.0.0.1") as client:
        result = client.post(
            "/api/v1/quarantine",
            headers=headers,
            json={
                "repo": "a/b",
                "nodeid": "test_a.py::test_a",
                "source_hash": "a" * 64,
                "owner": "backend",
                "issue": "ISSUE-1",
                "reason": "Investigate the recorded retries",
                "ttl_days": 1,
            },
        )
        assert result.status_code == 200
        entry = result.json()
        url = "/api/v1/quarantine/" + entry["id"]
        renewal = {
            "expected_version": 1,
            "reason": "Owner has reviewed the still-open problem",
            "ttl_days": 7,
        }
        updated = client.post(url + "/renew", headers=headers, json=renewal)
        assert updated.status_code == 200 and updated.json()["version"] == 2
        assert client.post(url + "/renew", headers=headers, json=renewal).status_code == 409
        revoked = client.post(
            url + "/revoke",
            headers=headers,
            json={
                "expected_version": 2,
                "reason": "Fix has now been independently reviewed",
                "ttl_days": 1,
            },
        )
        assert revoked.status_code == 200 and revoked.json()["revoked_at"]
        audit = client.get(url + "/audit", headers=headers).json()["entries"]
        assert [e["version"] for e in audit] == [1, 2, 3]
        assert all(e["actor"] == "reviewer" for e in audit)
        assert client.get(url + "/audit?workspace=other", headers=headers).status_code == 403


def test_shared_instance_does_not_claim_cross_tenant_os_isolation(tmp_path):
    credential = tmp_path / "credentials.json"
    credential.write_text(
        json.dumps(
            [
                {
                    "subject": "operator",
                    "sha256": "a" * 64,
                    "workspaces": ["one", "two"],
                    "scopes": ["analyze"],
                },
            ],
        ),
    )
    with pytest.raises(ValueError, match="One workspace"):
        create_app(Settings(profile="shared", allow_remote=True, credentials_file=credential))
