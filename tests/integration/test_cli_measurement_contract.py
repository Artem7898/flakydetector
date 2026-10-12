"""Use the actual CLI adapter and transports; source-import, not wheel-install proof."""

from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from flakydetector.cli import main


@pytest.mark.parametrize("transport", ["file", "directory", "zip"])
def test_same_source_has_same_identity_and_units_across_cli_inputs(tmp_path, capsys, transport):
    source = "import time\ndef test_wait():\n    time.sleep(1)\n"
    target = tmp_path / "test_sample.py"
    target.write_text(source)
    path = target
    if transport == "directory":
        path = tmp_path
    elif transport == "zip":
        path = tmp_path / "tests.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("test_sample.py", source)
    assert main([str(path), "--format", "json", "--fail-on", "none"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "3.0.0"
    assert payload["files_selected"] == payload["files_parsed"] == payload["test_candidates"] == 1
    assert payload["files_rejected"] == 0
    assert payload["source_snapshots"] == []
    assert (
        payload["source_digests"]["test_sample.py"] == hashlib.sha256(source.encode()).hexdigest()
    )
    assert payload["results"][0]["verdict"] == "risk_detected"


def test_cli_syntax_failure_cannot_be_disabled_by_risk_policy(tmp_path, capsys):
    target = tmp_path / "test_bad.py"
    target.write_text("def broken(:\n")
    assert main([str(target), "--format", "json", "--fail-on", "none"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["files_rejected"] == 1 and payload["files_parsed"] == 0
    assert payload["test_candidates"] == 0 and payload["diagnostic_groups"] == 1


def test_cli_risk_policy_and_text_explanation(tmp_path, capsys):
    target = tmp_path / "test_wait.py"
    target.write_text("import time\ndef test_wait():\n    time.sleep(1)\n")
    assert main([str(target), "--fail-on", "medium"]) == 1
    assert "FD-TIME-001" in capsys.readouterr().out


def test_cli_missing_input_is_error_not_success(tmp_path, capsys):
    assert main([str(tmp_path / "absent.py"), "--fail-on", "none"]) == 2
    assert "input rejected" in capsys.readouterr().err
