"""Общие фикстуры для тестов FlakyDetector."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Pytest plugin registration
# IMPORTANT:
# Do NOT use ".py" extension here.
pytest_plugins = [
    "flakydetector.ci_integration",
]

# ──────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SRC_ROOT = PROJECT_ROOT / "src"


# ──────────────────────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture()
def simple_sleep_code() -> str:
    """Code sample with time.sleep()."""

    return """
import time

def test_flaky_sleep():
    time.sleep(0.5)
    assert True
"""


@pytest.fixture()
def simple_sleep_ast(
    simple_sleep_code: str,
) -> ast.Module:
    """AST tree for simple_sleep_code."""

    return ast.parse(simple_sleep_code)


@pytest.fixture()
def multi_pattern_code() -> str:
    """Code with multiple flaky patterns."""

    return """
import time
import random

from datetime import datetime

global_counter = 0


def test_multi_flaky():
    global global_counter

    global_counter += 1

    time.sleep(random.random())

    now = datetime.now()

    assert global_counter > 0
"""


@pytest.fixture()
def clean_code() -> str:
    """Clean non-flaky test."""

    return """
def test_clean():
    assert 1 + 1 == 2
"""


@pytest.fixture()
def flaky_samples_dir() -> Path:
    """Path to tests/flaky_samples."""

    return (
        PROJECT_ROOT
        / "tests"
        / "flaky_samples"
    )


@pytest.fixture()
def async_flaky_path(
    flaky_samples_dir: Path,
) -> Path:
    """Path to async_flaky.py."""

    path = flaky_samples_dir / "async_flaky.py"

    if not path.exists():

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            """
import asyncio

async def test_async_flaky():
    await asyncio.sleep(0.1)
    assert True
""",
            encoding="utf-8",
        )

    return path


@pytest.fixture()
def timing_flaky_path(
    flaky_samples_dir: Path,
) -> Path:
    """Path to timing_flaky.py."""

    path = flaky_samples_dir / "timing_flaky.py"

    if not path.exists():

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            """
import time

def test_timing_flaky():
    time.sleep(1.0)
    assert True
""",
            encoding="utf-8",
        )

    return path


@pytest.fixture()
def temp_output_dir(
    tmp_path: Path,
) -> Path:
    """Temporary output directory."""

    output = tmp_path / "flaky_output"

    output.mkdir(exist_ok=True)

    return output