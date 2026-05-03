"""CI log analysis for flaky test detection."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from flakydetector.models.domain import (
    FlakyCategory,
    FlakySeverity,
    LogAnomaly,
    LogEntry,
    TestRunResult,
    TestRunStatus,
)
from flakydetector.utils.logger import get_logger

logger = get_logger(__name__)


# Common patterns for detecting flaky behavior in logs
FLAKY_LOG_PATTERNS: dict[str, dict[str, Any]] = {
    "timeout": {
        "pattern": r"(?i)(timeout|timed?\s*out)\s+(after|exceeded|waiting)",
        "category": FlakyCategory.TIMING_DEPENDENCY,
        "severity": FlakySeverity.HIGH,
        "description": "Timeout detected - test may be timing-dependent",
        "confidence": 0.8,
    },
    "connection_error": {
        "pattern": r"(?i)(connection\s*(refused|reset|timeout|error)|network\s*(error|unreachable))",
        "category": FlakyCategory.NETWORK_DEPENDENCY,
        "severity": FlakySeverity.HIGH,
        "description": "Network connection error - external dependency",
        "confidence": 0.85,
    },
    "port_in_use": {
        "pattern": r"(?i)(address\s*already\s*in\s*use|port\s*\d+\s*(is|already)\s*(in\s*use|taken|bound))",
        "category": FlakyCategory.GLOBAL_STATE,
        "severity": FlakySeverity.HIGH,
        "description": "Port conflict - resource not properly released",
        "confidence": 0.9,
    },
    "race_condition": {
        "pattern": r"(?i)(race\s*condition|concurrent\s*modification|deadlock)",
        "category": FlakyCategory.ASYNC_RACE_CONDITION,
        "severity": FlakySeverity.CRITICAL,
        "description": "Race condition or deadlock detected",
        "confidence": 0.95,
    },
    "resource_leak": {
        "pattern": r"(?i)(too\s*many\s*open\s*files|file\s*descriptor\s*limit|out\s*of\s*memory)",
        "category": FlakyCategory.RESOURCE_LEAK,
        "severity": FlakySeverity.CRITICAL,
        "description": "Resource leak detected",
        "confidence": 0.9,
    },
    "database_error": {
        "pattern": r"(?i)(database\s*is\s*locked|deadlock\s*found|serialization\s*failure)",
        "category": FlakyCategory.CONCURRENT_ACCESS,
        "severity": FlakySeverity.HIGH,
        "description": "Database concurrency error",
        "confidence": 0.85,
    },
    "flaky_retry": {
        "pattern": r"(?i)(retry|rerun|flaky)\s*(attempt|test|#\d+)",
        "category": FlakyCategory.UNKNOWN,
        "severity": FlakySeverity.MEDIUM,
        "description": "Test was retried - already known as flaky",
        "confidence": 0.7,
    },
    "timing_variance": {
        "pattern": r"(?i)(took\s+\d+ms|duration:\s*\d+\.\d+s|elapsed\s+time)",
        "category": FlakyCategory.TIMING_DEPENDENCY,
        "severity": FlakySeverity.LOW,
        "description": "Timing information found",
        "confidence": 0.3,
    },
}


class LogParser:
    """Parse CI logs into structured entries."""

    # Common log formats
    LOG_FORMATS = [
        # pytest
        re.compile(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"
            r"\s*\[?(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL|FAILED|PASSED)\]?"
            r"\s*(?P<message>.*)"
        ),
        # GitHub Actions
        re.compile(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)"
            r"\s+(?P<level>\w+)"
            r"\s+(?P<message>.*)"
        ),
        # Generic
        re.compile(
            r"(?P<message>.*)"
        ),
    ]

    # Test result patterns
    TEST_RESULT_PATTERN = re.compile(
        r"(?P<file>[\w/\.]+\.py)?(?::(?P<line>\d+))?\s*"
        r"(?P<test_name>test_\w+)"
    )

    def parse_log(self, log_content: str) -> list[LogEntry]:
        """Parse log content into structured entries."""
        entries: list[LogEntry] = []

        for line in log_content.splitlines():
            entry = self._parse_line(line)
            if entry:
                entries.append(entry)

        return entries

    def parse_log_file(self, file_path: Path) -> list[LogEntry]:
        """Parse log file."""
        if not file_path.exists():
            logger.warning("log_file_not_found", path=str(file_path))
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            return self.parse_log(content)
        except Exception as e:
            logger.error("log_parse_error", path=str(file_path), error=str(e))
            return []

    def _parse_line(self, line: str) -> LogEntry | None:
        """Parse a single log line."""
        if not line.strip():
            return None

        for fmt in self.LOG_FORMATS:
            match = fmt.match(line.strip())
            if match:
                groups = match.groupdict()

                timestamp = None
                if ts_str := groups.get("timestamp"):
                    try:
                        timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                # Extract test name
                test_match = self.TEST_RESULT_PATTERN.search(groups.get("message", ""))

                return LogEntry(
                    timestamp=timestamp,
                    level=groups.get("level", "INFO"),
                    message=groups.get("message", line),
                    test_name=test_match.group("test_name") if test_match else None,
                    file_path=test_match.group("file") if test_match else None,
                    line_number=int(test_match.group("line")) if test_match and test_match.group("line") else None,
                    raw_line=line,
                )

        return LogEntry(
            timestamp=None,
            level="INFO",
            message=line,
            test_name=None,
            file_path=None,
            line_number=None,
            raw_line=line,
        )


class LogAnalyzer:
    """Analyze CI logs for flaky test indicators."""

    def __init__(self) -> None:
        self._parser = LogParser()
        self._compiled_patterns: dict[str, re.Pattern] = {
            name: re.compile(config["pattern"])
            for name, config in FLAKY_LOG_PATTERNS.items()
        }

    def analyze_log(self, log_content: str) -> list[LogAnomaly]:
        """Analyze log content for anomalies."""
        entries = self._parser.parse_log(log_content)
        return self._detect_anomalies(entries)

    def analyze_log_file(self, file_path: Path) -> list[LogAnomaly]:
        """Analyze log file for anomalies."""
        entries = self._parser.parse_log_file(file_path)
        return self._detect_anomalies(entries)

    def analyze_multiple_runs(
            self,
            log_contents: list[str],
    ) -> dict[str, list[LogAnomaly]]:
        """Analyze multiple CI runs to detect intermittent failures."""
        all_anomalies: dict[str, list[LogAnomaly]] = defaultdict(list)

        for i, content in enumerate(log_contents):
            anomalies = self.analyze_log(content)
            for anomaly in anomalies:
                key = f"{anomaly.anomaly_type}:{anomaly.description[:50]}"
                all_anomalies[key].append(anomaly)

        # Filter to only intermittent issues (not present in all runs)
        intermittent = {
            k: v for k, v in all_anomalies.items()
            if len(v) < len(log_contents)
        }

        return dict(intermittent)

    def _detect_anomalies(self, entries: list[LogEntry]) -> list[LogAnomaly]:
        """Detect anomalies from parsed log entries."""
        anomalies: list[LogAnomaly] = []

        for entry in entries:
            for pattern_name, pattern in self._compiled_patterns.items():
                if pattern.search(entry.message):
                    config = FLAKY_LOG_PATTERNS[pattern_name]

                    # Find related entries
                    related_entries = self._find_related_entries(entries, entry)

                    anomalies.append(
                        LogAnomaly(
                            anomaly_type=pattern_name,
                            category=config["category"],
                            severity=config["severity"],
                            description=config["description"],
                            log_entries=related_entries,
                            confidence=config["confidence"],
                            metadata={
                                "test_name": entry.test_name,
                                "file_path": entry.file_path,
                                "line_number": entry.line_number,
                            },
                        )
                    )

        return anomalies

    def _find_related_entries(
            self,
            entries: list[LogEntry],
            target: LogEntry,
            window: int = 5,
    ) -> list[LogEntry]:
        """Find log entries related to the target entry."""
        try:
            idx = entries.index(target)
        except ValueError:
            return [target]

        start = max(0, idx - window)
        end = min(len(entries), idx + window + 1)
        return entries[start:end]

    def extract_test_results(self, log_content: str) -> list[TestRunResult]:
        """Extract test run results from log content."""
        entries = self._parser.parse_log(log_content)
        results: list[TestRunResult] = []

        for entry in entries:
            if not entry.test_name:
                continue

            # Determine status from log level
            status_map = {
                "PASSED": TestRunStatus.PASSED,
                "FAILED": TestRunStatus.FAILED,
                "ERROR": TestRunStatus.ERROR,
                "SKIPPED": TestRunStatus.SKIPPED,
            }
            status = status_map.get(entry.level.upper(), TestRunStatus.PASSED)

            # Extract duration if present
            duration_ms = 0.0
            duration_match = re.search(r"(\d+(?:\.\d+)?)\s*(ms|s)", entry.message)
            if duration_match:
                value = float(duration_match.group(1))
                if duration_match.group(2) == "s":
                    value *= 1000
                duration_ms = value

            results.append(
                TestRunResult(
                    test_name=entry.test_name,
                    status=status,
                    duration_ms=duration_ms,
                    timestamp=entry.timestamp or datetime.utcnow(),
                )
            )

        return results