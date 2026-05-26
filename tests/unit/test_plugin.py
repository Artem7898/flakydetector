"""Тесты для плагина pytest-flaky-trail."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from flakydetector.pytest_flaky_trail.storage import TrailStorage


def test_storage_creates_db(tmp_path: Path) -> None:
    """Проверяем, что хранилище корректно создаёт таблицы."""
    db_file = tmp_path / "test.db"
    storage = TrailStorage(db_path=db_file)

    assert db_file.exists()

    # Проверяем наличие таблиц через прямой SQL запрос
    conn = sqlite3.connect(db_file)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='test_trails'"
    )
    assert cursor.fetchone() is not None
    conn.close()


def test_storage_saves_trail(tmp_path: Path) -> None:
    """Проверяем запись трейла в БД."""
    storage = TrailStorage(db_path=tmp_path / "test2.db")
    run_id = storage.start_run(repo_name="test_repo")

    storage.save_trail(
        run_id=run_id,
        nodeid="tests/test_foo.py::test_bar",
        outcome="failed",
        duration=0.123,
        traceback="AssertionError: assert 1 == 2"
    )

    conn = sqlite3.connect(tmp_path / "test2.db")
    cursor = conn.execute("SELECT outcome, duration FROM test_trails")
    row = cursor.fetchone()
    conn.close()

    assert row == ("failed", 0.123)