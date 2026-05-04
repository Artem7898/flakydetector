"""CLI tool to scan entire directories for flaky test patterns."""

from __future__ import annotations

import sys
from pathlib import Path
import argparse
from rich.console import Console
from rich.table import Table

# Добавляем корень проекта в путь для импорта
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from flakydetector.analyzer.ast_analyzer import ASTAnalyzer

console = Console()


def scan_directory(target_path: str) -> None:
    """Scan a directory and print a formatted report."""
    target_dir = Path(target_path)

    if not target_dir.exists():
        console.print(f"[red]Error: Directory '{target_dir}' does not exist.[/red]")
        sys.exit(1)
    if not target_dir.is_dir():
        console.print(f"[red]Error: '{target_dir}' is not a directory.[/red]")
        sys.exit(1)

    console.print(f"[bold blue]🔍 Scanning: {target_dir.resolve()}...[/bold blue]\n")

    analyzer = ASTAnalyzer(max_file_size=1_000_000)

    # Запускаем сканирование. Ищем все файлы test_*.py
    results = analyzer.analyze_directory(target_dir, pattern="**/test_*.py")

    if not results:
        console.print("[bold green]✅ No flaky patterns found in scanned files.[/bold green]")
        return

    # Формируем красивую таблицу
    table = Table(title="Flaky Patterns Detected", show_lines=True)
    table.add_column("File", style="cyan", no_wrap=False, max_width=40)
    table.add_column("Line", justify="right", style="white", width=5)
    table.add_column("Pattern", style="yellow", max_width=25)
    table.add_column("Severity", justify="center", width=10)
    table.add_column("Confidence", justify="right", style="green", width=10)

    total_patterns = 0
    for file_path, patterns in results.items():
        for p in patterns:
            # Цветовая кодировка severe
            severity_style = "red" if p.severity.value in ("high", "critical") else "white"
            table.add_row(
                file_path,
                str(p.location.line_start),
                p.pattern_type,
                f"[{severity_style}]{p.severity.value.upper()}[/{severity_style}]",
                f"{p.confidence:.0%}"
            )
            total_patterns += 1

    console.print(table)
    console.print(f"\n[bold]Summary:[/bold] {len(results)} affected files, {total_patterns} total patterns.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan Python tests for flaky patterns.")
    parser.add_argument("target_path", help="Path to the directory to scan")
    parser.add_argument(
        "--fail-on-critical",
        action="store_true",
        help="Exit with code 1 if CRITICAL severity patterns are found (for CI)"
    )

    args = parser.parse_args()

    # Перехватываем вывод, чтобы проанализировать результаты для CI
    target_dir = Path(args.target_path)
    analyzer = ASTAnalyzer(max_file_size=1_000_000)
    results = analyzer.analyze_directory(target_dir, pattern="**/test_*.py")

    # Выводим красивую таблицу
    scan_directory(args.target_path)

    # CI LOGIC: Проверяем, есть ли критические паттерны
    if args.fail_on_critical and results:
        has_critical = any(
            p.severity.value == "critical"
            for patterns in results.values()
            for p in patterns
        )
        if has_critical:
            console.print("\n[bold red]🚫 CI FAILED: Critical flaky patterns detected. PR is blocked.[/bold red]")
            sys.exit(1)

    sys.exit(0)  # Успешное завершение