"""Real local HTTP transport: explicit uploads strip traces and reject redirects."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from flakydetector.runtime.store import EvidenceStore
from flakydetector.runtime.upload import upload_events
from tests.unit.test_product_core import events


@pytest.fixture
def upload_server():
    requests = []
    config = {"status": 200, "receipt": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers.get("Authorization"), body))
            self.send_response(config["status"])
            if config["status"] == 307:
                self.send_header("Location", "/untrusted-target")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    config["receipt"] or {"added": len(body["events"]), "duplicates": 0}
                ).encode(),
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (f"http://127.0.0.1:{server.server_port}", requests, config)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_upload_pages_preserves_event_ids_but_never_tracebacks(tmp_path, upload_server):
    url, requests, _ = upload_server
    store = EvidenceStore(tmp_path / "events.db")
    rows = [event.model_copy(update={"traceback": "token=SYNTHETIC_CANARY"}) for event in events()]
    store.ingest(rows, workspace="local")
    assert upload_events(
        store,
        workspace="local",
        repo="a/b",
        url=url,
        token="explicit-test-token",
        batch_size=2,
    ) == {"added": 3, "duplicates": 0}
    assert len(requests) == 2
    assert requests[0][1] == "Bearer explicit-test-token"
    uploaded = [event for _, _, body in requests for event in body["events"]]
    assert {event["event_id"] for event in uploaded} == {event.event_id for event in rows}
    assert all(event["traceback"] is None for event in uploaded)


@pytest.mark.parametrize(
    "receipt",
    [
        {"added": 0, "duplicates": 0},
        {"added": -1, "duplicates": 4},
        {"added": "3", "duplicates": 0},
        {"added": True, "duplicates": 2},
    ],
)
def test_invalid_receipts_fail(tmp_path, upload_server, receipt):
    url, _, config = upload_server
    config["receipt"] = receipt
    store = EvidenceStore(tmp_path / "events.db")
    store.ingest(events(), workspace="local")
    with pytest.raises(ValueError):
        upload_events(store, workspace="local", repo="a/b", url=url, token="")


def test_upload_never_follows_redirect_with_token(tmp_path, upload_server):
    url, requests, config = upload_server
    config["status"] = 307
    store = EvidenceStore(tmp_path / "events.db")
    store.ingest(events(), workspace="local")
    with pytest.raises(ValueError, match="Redirect"):
        upload_events(store, workspace="local", repo="a/b", url=url, token="test-token")
    assert len(requests) == 1


@pytest.mark.parametrize(
    "url,token,remote,batch",
    [
        ("http://example.invalid", "test", True, 500),
        ("https://example.invalid", "", True, 500),
        ("https://example.invalid", "test", False, 500),
        ("ftp://example.invalid", "test", True, 500),
        ("http://user:password@127.0.0.1", "", False, 500),
        ("http://127.0.0.1/?key=secret", "", False, 500),
        ("http://127.0.0.1", "", False, 0),
        ("http://127.0.0.1", "", False, 2001),
    ],
)
def test_upload_validates_policy_before_network(tmp_path, url, token, remote, batch):
    with pytest.raises(ValueError):
        upload_events(
            EvidenceStore(tmp_path / "empty.db"),
            workspace="local",
            repo="a/b",
            url=url,
            token=token,
            allow_remote=remote,
            batch_size=batch,
        )
