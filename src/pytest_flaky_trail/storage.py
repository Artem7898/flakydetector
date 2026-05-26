"""SQLite хранилище для трейлов тестов."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TrailStorage:
    def __init__(self, db_path: str | Path = "flaky_trails.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        # Ускоряем запись, так как нас интересует сбор данных, а не транзакционная целостность на миллисекунды
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS test_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_timestamp TEXT NOT NULL,
                    repo_name TEXT,
                    environment TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS test_trails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    nodeid TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    duration REAL NOT NULL,
                    traceback TEXT,
                    FOREIGN KEY (run_id) REFERENCES test_runs (id)
                )
            """)

    def start_run(self, repo_name: str = "unknown", env: str = "local") -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO test_runs (run_timestamp, repo_name, environment) VALUES (?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), repo_name, env)
            )
            return cursor.lastrowid

    def save_trail(
        self,
        run_id: int,
        nodeid: str,
        outcome: str,
        duration: float,
        traceback: str | None
    ) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO test_trails 
                   (run_id, nodeid, outcome, duration, traceback) 
                   VALUES (?, ?, ?, ?, ?)""",
                (run_id, nodeid, outcome, duration, traceback)
            )