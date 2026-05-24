"""Zero-Downtime integration with FlakyDetector."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Stable absolute plugin path
PLUGIN_PATH = (
    Path(__file__).parent
    / "flaky_integration"
).resolve()

# Prevent duplicate sys.path injection
if str(PLUGIN_PATH) not in sys.path:
    sys.path.insert(0, str(PLUGIN_PATH))

# Use ONE canonical import style
from trap_shared_state import SharedStateTrap

import flaky_integration.fixture_parser as fp


def pytest_configure(config: pytest.Config) -> None:
    """
    Activate FixtureParser after pytest bootstrap.

    Prevents circular import issues during startup.
    """

    parser = fp.FixtureParser()

    if hasattr(parser, "activate"):
        parser.activate()


@pytest.fixture(autouse=True)
def _shared_state_trap() -> SharedStateTrap:
    """
    Automatically attach shared state tracker.
    """

    return SharedStateTrap()