"""Run the action driver against real temporary Git repositories, never GitHub mocks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _fixture_git_env() -> dict[str, str]:
    """Isolate test subprocesses without modifying the user's Git configuration."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_ATTR_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        LC_ALL="C",
    )
    # These options apply only to the fixture and its Action subprocess tree.
    # The real repository's signing, hooks and protected-branch rules are unchanged.
    options = {
        "commit.gpgSign": "false",
        "tag.gpgSign": "false",
        "core.hooksPath": os.devnull,
        "core.excludesFile": os.devnull,
        "core.attributesFile": os.devnull,
        "core.autocrlf": "false",
        "core.safecrlf": "false",
        "init.templateDir": "",
        "user.useConfigOnly": "true",
    }
    env["GIT_CONFIG_COUNT"] = str(len(options))
    for index, (key, value) in enumerate(options.items()):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


def git(root: Path, *args: str) -> str:
    """Run real Git; surface captured stderr on failure, never skip a failed commit."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            env=_fixture_git_env(),
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"Git fixture command timed out after {exc.timeout}s: git {args!r}")
    except OSError as exc:
        pytest.fail(f"Cannot start Git fixture command: {exc}")
    if result.returncode != 0:
        pytest.fail(
            f"Git fixture command failed (exit {result.returncode}): git {args!r}\n"
            f"cwd: {root}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            pytrace=False,
        )
    return result.stdout.strip()


def repository(tmp_path):
    root = tmp_path / "target"
    root.mkdir()
    git(root, "init", "-q", "--template=", "--initial-branch=main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    marker = tmp_path / "untrusted-module-executed"
    (root / "pydantic.py").write_text(
        f'open({str(marker)!r},"w").write("executed")\nraise RuntimeError("untrusted import")',
    )
    (root / ".env").write_text("SECRET=CANARY_PRIVATE_VALUE\n")
    (root / "test_case.py").write_text(
        'import requests\ndef test_request():\n    requests.get("https://example.invalid")\n',
    )
    git(root, "add", ".")
    git(root, "commit", "-qm", "trusted base fixture")
    return (root, marker, git(root, "rev-parse", "HEAD"))


def run_action(root, tmp_path, base, event="workflow_dispatch"):
    output = tmp_path / "outputs.txt"
    summary = tmp_path / "summary.md"
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"pull_request": {"base": {"sha": base}}}))
    env = {
        **_fixture_git_env(),
        "GITHUB_WORKSPACE": str(root),
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_EVENT_NAME": event,
        "GITHUB_EVENT_PATH": str(event_path),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "scripts/action_runner.py"),
            "--scope",
            ".",
            "--base",
            base,
        ],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    values = (
        dict(line.split("=", 1) for line in output.read_text().splitlines())
        if output.exists()
        else {}
    )
    return (result, values)


def test_action_uses_trusted_tool_and_base_not_target_imports(tmp_path):
    root, marker, base = repository(tmp_path)
    source = (root / "test_case.py").read_text()
    (root / "test_case.py").write_text("\n\n" + source)
    result, values = run_action(root, tmp_path, base, event="pull_request")
    assert result.returncode == 0, result.stdout + result.stderr
    assert values["exit_code"] == "0" and (not marker.exists())
    sarif = json.loads(Path(values["sarif"]).read_text())
    assert sarif["runs"][0]["results"][0]["baselineState"] == "unchanged"
    assert "CANARY_PRIVATE_VALUE" not in Path(values["sarif"]).read_text()


def test_action_preserves_risk_exit_and_complete_sarif(tmp_path):
    root, marker, base = repository(tmp_path)
    with (root / "test_case.py").open("a") as stream:
        stream.write('\ndef test_new():\n    requests.post("https://example.invalid")\n')
    result, values = run_action(root, tmp_path, base)
    assert result.returncode == 0, result.stdout + result.stderr
    assert values["exit_code"] == "1" and (not marker.exists())
    states = [
        r["baselineState"]
        for r in json.loads(Path(values["sarif"]).read_text())["runs"][0]["results"]
    ]
    assert set(states) == {"new", "unchanged"}


def test_privileged_pull_request_target_is_rejected(tmp_path):
    root, marker, base = repository(tmp_path)
    result, values = run_action(root, tmp_path, base, event="pull_request_target")
    assert result.returncode != 0 and (not values) and (not marker.exists())


def test_git_fixture_ignores_user_signing_and_hooks(tmp_path, monkeypatch):
    home = tmp_path / "fake-home"
    home.mkdir()
    hooks = tmp_path / "user-hooks"
    hooks.mkdir()
    hook_marker = tmp_path / "user-hook-executed"
    hook = hooks / "pre-commit"
    hook.write_text(f'#!/bin/sh\necho hook > "{hook_marker}"\nexit 1\n')
    hook.chmod(0o755)
    config = home / ".gitconfig"
    content = (
        "[user]\n\tname = Real User\n\temail = real@example.invalid\n"
        "[commit]\n\tgpgSign = true\n"
        f'[gpg]\n\tprogram = "{tmp_path / "missing-signing-tool"}"\n'
        f'[core]\n\thooksPath = "{hooks}"\n'
    )
    config.write_text(content)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    root, marker, base = repository(tmp_path)
    assert git(root, "rev-parse", "HEAD") == base
    assert git(root, "log", "-1", "--format=%an <%ae>") == "Test <test@example.invalid>"
    assert config.read_text() == content
    assert not hook_marker.exists()
    assert not marker.exists()


def test_git_fixture_ignores_routing_and_inline_config(tmp_path, monkeypatch):
    external_index = tmp_path / "unrelated-index"
    external_index.write_text("DO NOT TOUCH")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "not-a-repository"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "not-a-worktree"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(external_index))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "")
    monkeypatch.setenv("GIT_AUTHOR_DATE", "not-a-valid-date")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "commit.gpgSign")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    root, marker, base = repository(tmp_path)
    assert git(root, "rev-parse", "HEAD") == base
    assert external_index.read_text() == "DO NOT TOUCH"
    # The Action's Git reads must use this same isolated test environment.
    result, values = run_action(root, tmp_path, base, event="pull_request")
    assert result.returncode == 0, result.stdout + result.stderr
    assert values["exit_code"] == "0"
    assert not marker.exists()
    assert os.environ["GIT_DIR"] == str(tmp_path / "not-a-repository")


def test_git_fixture_ignores_global_excludes_and_templates(tmp_path, monkeypatch):
    home = tmp_path / "fake-home"
    git_config_dir = home / ".config" / "git"
    git_config_dir.mkdir(parents=True)
    (git_config_dir / "ignore").write_text("*\n")
    template = tmp_path / "user-template"
    (template / "hooks").mkdir(parents=True)
    hook = template / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(template))
    root, marker, _ = repository(tmp_path)
    assert not (root / ".git" / "hooks" / "pre-commit").exists()
    assert set(git(root, "ls-files").splitlines()) == {".env", "pydantic.py", "test_case.py"}
    assert not marker.exists()


def test_git_fixture_rejects_real_git_failure_with_stderr(tmp_path):
    root, _, _ = repository(tmp_path)
    with pytest.raises(pytest.fail.Exception, match="stderr:") as caught:
        git(root, "rev-parse", "--verify", "missing-ref-for-fixture-test")
    assert "exit 128" in str(caught.value)
    assert "fatal:" in str(caught.value)


def test_git_fixture_reports_timeout(monkeypatch, tmp_path):
    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", time_out)
    with pytest.raises(pytest.fail.Exception, match="timed out"):
        git(tmp_path, "status")


def test_git_fixture_reports_missing_executable(monkeypatch, tmp_path):
    def missing(*args, **kwargs):
        raise FileNotFoundError("git executable unavailable in synthetic test")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(pytest.fail.Exception, match="Cannot start Git"):
        git(tmp_path, "status")


def test_git_fixture_environment_does_not_change_parent(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "poisoned parent settings")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "999")
    monkeypatch.setenv("GITHUB_WORKSPACE", "preserved-workspace")
    before = dict(os.environ)
    env = _fixture_git_env()
    assert dict(os.environ) == before
    assert "GIT_CONFIG_PARAMETERS" not in env
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GITHUB_WORKSPACE"] == "preserved-workspace"
    assert env["GIT_CONFIG_COUNT"] != "999"
