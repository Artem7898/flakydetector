"""pytest plugin for dynamic tracing of test execution and shared state."""

from __future__ import annotations


import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import pytest


class FlakyTrailPlugin:
    """Tracks test execution order, results, and intercepts shared state mutations."""

    def __init__(self) -> None:
        self.db_path = Path("data/raw/traces.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_id: str = uuid.uuid4().hex[:8]
        self._current_test_index: int = 0
        self._last_test_name: str | None = None
        self._last_test_time: float = 0.0
        _is_active: bool = False

    def activate(self) -> None:
        self._run_id = uuid.uuid4().hex[:8]
        self._is_active = True
        self._current_test_index = 0
        self._last_test_name = None
        self._last_test_time = 0.0

    def record_test_result(
            self, test_name: str, status: str, duration_ms: float
    ) -> None:
        if not self._is_active:
            return

        prev_name = self._last_test_name
        prev_time = self._last_test_time
        prev_failed = status in ("failed", "error")

        # Write to database
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO test_runs (run_id, test_name, status, duration_ms, timestamp, prev_test_failed, prev_test_name, prev_time_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self._run_id, test_name, status, duration_ms, time.time(),
                        1 if prev_failed else 0, prev_name, prev_time
                    ),
                )
            conn.commit()
        except sqlite3.Error as e:
            print(f"[FlakyTrail] DB Error: {e}")

        self._last_test_name = test_name
        self._last_test_time = time.time()
        self._current_test_index += 1


# --- Pytest Hooks Setup ---

trail_plugin = FlakyTrailPlugin()


def pytest_configure(config: Any) -> None:
    """Setup hook to initialize the plugin and SQLite schema."""
    trail_plugin.activate()

    try:
        with sqlite3.connect(trail_plugin.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS test_runs (
                    run_id TEXT,
                    test_name TEXT,
                    status TEXT,
                    duration_ms REAL,
                    timestamp REAL,
                    prev_test_failed INTEGER DEFAULT 0,
                    prev_test_name TEXT,
                    prev_time_ms REAL DEFAULT 0.0
                )
            """)
            conn.commit()
    except sqlite3.Error as __:
        pass


def pytest_runtest_makereport(item: Any, call: Any) -> None:
    """Post-test hook to record execution trace."""
    status = "passed"
    if call.excinfo is not None:
        status = "failed" if call.excinfo.typename != "Skipped" else "error"

    duration_ms = (call.stop - call.start) * 1000.0 if hasattr(call, "stop") else 0.0
    test_name = item.name

    trail_plugin.record_test_result(test_name, status, duration_ms)