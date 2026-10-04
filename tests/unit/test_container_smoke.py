"""Readiness retry regressions, including a real loopback TCP reset (not Docker)."""

from __future__ import annotations

import importlib.util
import json
import socket
import struct
import subprocess
import threading
import urllib.error
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def smoke(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "container_smoke_tests", ROOT / "scripts/container_smoke.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ready_clock(smoke, monkeypatch):
    class Clock:
        now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            assert seconds > 0
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(smoke, "time", clock)
    monkeypatch.setattr(smoke, "run", Mock(return_value=json.dumps({"Running": True})))
    return clock


@pytest.mark.parametrize(
    "error",
    [
        ConnectionResetError(104, "Connection reset by peer"),
        ConnectionRefusedError(111, "Connection refused"),
        TimeoutError("startup request timed out"),
        urllib.error.URLError("connection not ready"),
    ],
)
def test_transient_readiness_errors_retry(smoke, ready_clock, monkeypatch, error):
    probe = Mock(side_effect=[error, nullcontext(SimpleNamespace(status=200))])
    monkeypatch.setattr(smoke.urllib.request, "urlopen", probe)
    smoke.wait_for_ready("http://127.0.0.1/ready", "smoke-container", timeout=5)
    assert probe.call_count == 2
    assert ready_clock.now == 1.0


@pytest.mark.parametrize("status", [502, 503, 504])
def test_startup_http_unavailability_retries(smoke, ready_clock, monkeypatch, status):
    error = urllib.error.HTTPError("http://127.0.0.1/ready", status, "not ready", {}, None)
    probe = Mock(side_effect=[error, nullcontext(SimpleNamespace(status=200))])
    monkeypatch.setattr(smoke.urllib.request, "urlopen", probe)
    smoke.wait_for_ready("http://127.0.0.1/ready", "smoke-container", timeout=5)
    assert probe.call_count == 2


@pytest.mark.parametrize("status", [401, 404, 500])
def test_wrong_route_auth_or_internal_error_is_not_hidden(smoke, ready_clock, monkeypatch, status):
    error = urllib.error.HTTPError("http://127.0.0.1/ready", status, "failure", {}, None)
    probe = Mock(side_effect=error)
    monkeypatch.setattr(smoke.urllib.request, "urlopen", probe)
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        smoke.wait_for_ready("http://127.0.0.1/ready", "smoke-container", timeout=5)
    assert probe.call_count == 1
    assert ready_clock.now == 0


def test_persistent_reset_fails_at_deadline(smoke, ready_clock, monkeypatch):
    probe = Mock(side_effect=ConnectionResetError(104, "Connection reset by peer"))
    monkeypatch.setattr(smoke.urllib.request, "urlopen", probe)
    with pytest.raises(RuntimeError, match=r"within 2.5s: ConnectionResetError"):
        smoke.wait_for_ready("http://127.0.0.1/ready", "smoke-container", timeout=2.5)
    assert probe.call_count == 3
    assert ready_clock.now == 2.5


def test_stopped_container_fails_without_waiting(smoke, ready_clock, monkeypatch):
    monkeypatch.setattr(
        smoke, "run", Mock(return_value=json.dumps({"Running": False, "ExitCode": 1}))
    )
    probe = Mock()
    monkeypatch.setattr(smoke.urllib.request, "urlopen", probe)
    with pytest.raises(RuntimeError, match="Container exited before readiness"):
        smoke.wait_for_ready("http://127.0.0.1/ready", "smoke-container")
    probe.assert_not_called()
    assert ready_clock.now == 0


@pytest.mark.parametrize("options", [{"timeout": 0}, {"timeout": -1}, {"interval": 0}])
def test_invalid_wait_configuration_is_rejected(smoke, options):
    with pytest.raises(ValueError, match="must be positive"):
        smoke.wait_for_ready("http://127.0.0.1/ready", "smoke-container", **options)


def test_failed_build_still_writes_its_log(smoke, monkeypatch, tmp_path):
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        Mock(
            return_value=subprocess.CompletedProcess(
                ["docker", "build"],
                1,
                stdout="build output\n",
                stderr="build failure\n",
            )
        ),
    )
    log = tmp_path / "container.build.log"
    with pytest.raises(RuntimeError, match="Command failed"):
        smoke.run(["docker", "build"], log_path=log)
    assert log.read_text() == "build output\nbuild failure\n"


def test_real_loopback_reset_then_ready(smoke, monkeypatch):
    """Exercise urllib with a TCP RST, but never call a real Docker daemon."""

    class Handler(BaseHTTPRequestHandler):
        attempts = 0

        def do_GET(self):
            type(self).attempts += 1
            if type(self).attempts == 1:
                self.connection.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                )
                self.close_connection = True
                return
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    monkeypatch.setattr(smoke, "run", Mock(return_value=json.dumps({"Running": True})))
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            smoke.wait_for_ready(
                f"http://127.0.0.1:{server.server_port}/ready",
                "fake-docker",
                timeout=5,
                interval=0.01,
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)
    assert Handler.attempts == 2
