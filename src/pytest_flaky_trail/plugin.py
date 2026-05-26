"""Реализация хука pytest_runtest_makereport."""
from __future__ import annotations

from pathlib import Path

import pytest

from flakydetector.pytest_flaky_trail.storage import TrailStorage

# Глобальное хранилище на сессию
_storage: TrailStorage | None = None
_run_id: int = -1


def pytest_addoption(parser: pytest.Parser) -> None:
    """Добавляем CLI флаг для активации сбора трейлов."""
    parser.addoption(
        "--flaky-trail",
        action="store_true",
        default=False,
        help="Включить сбор трейлов тестов в SQLite для FlakyDetector"
    )
    parser.addoption(
        "--flaky-trail-db",
        action="store",
        default="flaky_trails.db",
        help="Путь к файлу SQLite базы данных (по умолчанию: flaky_trails.db)"
    )


def pytest_configure(config: pytest.Config) -> None:
    """Инициализация хранилища при старте сессии."""
    global _storage, _run_id

    if not config.getoption("--flaky-trail", skip=True):
        return

    db_path = config.getoption("--flaky_trail_db", skip=True)
    _storage = TrailStorage(db_path=db_path)

    # Пытаемся угадать имя репозитория по папке
    repo_name = Path.cwd().name
    _run_id = _storage.start_run(repo_name=repo_name)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    """Перехватываем результат КАЖДОГО теста (setup, call, teardown)."""
    global _storage, _run_id

    if _storage is None or _run_id == -1:
        yield
        return

    # Выполняем оригинальный хук и получаем отчёт
    outcome = yield
    report: pytest.TestReport = outcome.get_result()

    # Нас интересует только этап выполнения самого теста (не setup/teardown)
    if report.when == "call":
        _storage.save_trail(
            run_id=_run_id,
            nodeid=item.nodeid,
            outcome=report.outcome,  # 'passed', 'failed', 'skipped'
            duration=call.duration if call.duration else 0.0,
            traceback=str(report.longrepr) if report.failed else None
        )