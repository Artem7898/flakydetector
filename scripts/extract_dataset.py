"""
Экстрактор датасета из SQLite трейлов в JSONL формат для LLM/RAG.
Извлекает исходный код flaky-тестов через AST-парсинг.
"""
from __future__ import annotations

import ast
import json
import sqlite3
import sys
from pathlib import Path


def get_flaky_tests(db_path: str | Path) -> list[dict]:
    """Извлекает из БД тесты с миксом passed/failed и их трейсбэки."""
    query = """
    SELECT 
        t.nodeid, 
        SUM(CASE WHEN t.outcome='passed' THEN 1 ELSE 0 END) as passed,
        SUM(CASE WHEN t.outcome='failed' THEN 1 ELSE 0 END) as failed,
        GROUP_CONCAT(t.traceback, '|||') as tracebacks
    FROM test_trails t
    GROUP BY t.nodeid 
    HAVING failed > 0 AND passed > 0
    ORDER BY failed DESC;
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query)]


def extract_function_source(file_path: Path, func_name: str) -> str | None:
    """
    Безопасно извлекает исходный код функции через AST.
    Сеньор-комментарий: Мы не используем regex, потому что он сломается
    на вложенных функциях, декораторах или многострочных строках. AST дает точный срез.
    """
    if not file_path.exists():
        return None

    source_code = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                # ast.get_source_segment возвращает точный кусок текста
                return ast.get_source_segment(source_code, node)
    except SyntaxError:
        pass
    return None


def main(db_path: str, output_path: str):
    print(f"🔍 Анализируем трейлы в {db_path}...")
    flaky_tests = get_flaky_tests(db_path)

    if not flaky_tests:
        print("❌ Flaky тесты не найдены.")
        return

    print(f"✅ Найдено {len(flaky_tests)} flaky тестов. Извлекаем исходный код...")

    db_dir = Path(db_path).parent
    dataset_records = []

    for test in flaky_tests:
        nodeid = test["nodeid"]
        # Пример nodeid: 'test_flaky.py::test_real_flaky_by_random'
        parts = nodeid.split("::")
        if len(parts) < 2:
            continue

        file_name = parts[0]
        func_name = parts[1]
        file_path = db_dir / file_name

        source_code = extract_function_source(file_path, func_name)

        if not source_code:
            print(f"⚠️  Не удалось извлечь код для {nodeid}")
            continue

        total_runs = test["passed"] + test["failed"]
        flake_rate = round((test["failed"] / total_runs) * 100, 2)

        # Формируем запись датасета
        record = {
            "nodeid": nodeid,
            "source_code": source_code.strip(),
            "flakiness_rate_percent": flake_rate,
            "runs_total": total_runs,
            "sample_tracebacks": test["tracebacks"].split("|||") if test["tracebacks"] else []
        }
        dataset_records.append(record)

    # Записываем в JSONL
    with open(output_path, "w", encoding="utf-8") as f:
        for record in dataset_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"💾 Датасет сохранен в {output_path} ({len(dataset_records)} записей)")


if __name__ == "__main__":
    # По умолчанию берем ту БД, которую мы собрали на прошлом шаге
    DEFAULT_DB = str(Path("~/flaky_hunt/synthetic_flaky/synthetic_trails.db").expanduser())
    DEFAULT_OUT = "data/processed/flaky_dataset.jsonl"

    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT

    main(db, out)