from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_gate_for_tests", ROOT / "scripts/check_release.py")
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


@pytest.fixture(scope="module")
def released_files(tmp_path_factory):
    archive = tmp_path_factory.mktemp("release") / "candidate.zip"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_release.py"), "--output", str(archive)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return GATE.read_release(archive)


def test_actual_release_has_complete_manifest(released_files):
    assert released_files["LICENSE"].startswith(b"MIT License")
    assert json.loads(released_files[GATE.MANIFEST])["files"] == {
        name: hashlib.sha256(data).hexdigest()
        for name, data in released_files.items() if name != GATE.MANIFEST
    }


def test_missing_license_fails_even_with_other_valid_inputs(released_files):
    files = {name: data for name, data in released_files.items() if name != "LICENSE"}
    with pytest.raises(ValueError, match="Missing required file: LICENSE"):
        GATE.validate_entries(list(files.items()))


def test_final_byte_change_invalidates_report_identity(released_files):
    files = dict(released_files)
    files["README.md"] += b"\nchanged after verification\n"
    with pytest.raises(ValueError, match="manifest"):
        GATE.validate_entries(list(files.items()))


def test_unmanifested_new_file_is_not_accepted(released_files):
    with pytest.raises(ValueError, match="manifest"):
        GATE.validate_entries([*released_files.items(), ("new.txt", b"unexpected")])


@pytest.mark.parametrize("name", [".coverage", "src/__pycache__/test.pyc", "../outside.py", "/absolute.py", "src/../escape.py"])
def test_forbidden_or_unsafe_paths_fail(released_files, name):
    with pytest.raises(ValueError, match="Unsafe|Forbidden"):
        GATE.validate_entries([*released_files.items(), (name, b"not allowed")])


def test_duplicate_member_is_rejected(released_files):
    with pytest.raises(ValueError, match="Duplicate"):
        GATE.validate_entries([*released_files.items(), ("README.md", released_files["README.md"])])
