"""Parse explicit pytest outcomes; unknown text never becomes a passed test."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from flakydetector.models.domain import (
    FlakyCategory as C,
)
from flakydetector.models.domain import (
    FlakySeverity as S,
)
from flakydetector.models.domain import (
    LogAnomaly,
    LogEntry,
    TestRunResult,
    TestRunStatus,
)

# These are risk indicators, not observed-flaky labels.
LOG_RULES: dict[str, tuple[str, C, S, float]] = {
    "timeout": (
        r"(?i)(timeout|timed?\s*out)\s+(after|exceeded|waiting)",
        C.TIMING_DEPENDENCY,
        S.HIGH,
        0.8,
    ),
    "connection_error": (
        r"(?i)connection\s*(refused|reset|timeout|error)|network\s*(error|unreachable)",
        C.NETWORK_DEPENDENCY,
        S.HIGH,
        0.85,
    ),
    "port_in_use": (
        r"(?i)address\s*already\s*in\s*use|port\s*\d+\s*(is|already)\s*(in\s*use|taken|bound)",
        C.GLOBAL_STATE,
        S.HIGH,
        0.9,
    ),
    "race_condition": (
        r"(?i)race\s*condition|concurrent\s*modification|deadlock",
        C.ASYNC_RACE_CONDITION,
        S.HIGH,
        0.9,
    ),
    "resource_leak": (
        r"(?i)too\s*many\s*open\s*files|file\s*descriptor\s*limit|out\s*of\s*memory",
        C.RESOURCE_LEAK,
        S.HIGH,
        0.9,
    ),
    "database_error": (
        r"(?i)database\s*is\s*locked|deadlock\s*found|serialization\s*failure",
        C.CONCURRENT_ACCESS,
        S.HIGH,
        0.85,
    ),
    "flaky_retry": (
        r"(?i)(retry(?:ing)?|rerun|flaky)\s*(attempt|test|#\d+)",
        C.UNKNOWN,
        S.LOW,
        0.7,
    ),
}
STATUS = r"PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS|RERUN"
SUFFIX_RESULT = re.compile(rf"(?P<node>[^\s:]+\.py::.+?)\s+(?P<status>{STATUS})(?:\s|\[|$)")
PREFIX_RESULT = re.compile(
    rf"\b(?P<status>{STATUS})\s+(?P<node>[^\s:]+\.py::.+?)(?:\s+-\s+|\s+\[\s*\d+%|$)"
)
LEVEL = re.compile(rf"\[(?P<status>{STATUS})\]\s*(?P<node>[^\s:]+\.py::[^\r\n]+?)(?:\s+-\s+|$)")
NODEID = re.compile(r"(?P<node>[^\s:]+\.py::[^\s]+)")
STATUS_MAP = {
    "PASSED": TestRunStatus.PASSED,
    "FAILED": TestRunStatus.FAILED,
    "ERROR": TestRunStatus.ERROR,
    "SKIPPED": TestRunStatus.SKIPPED,
    "XFAIL": TestRunStatus.XFAILED,
    "XPASS": TestRunStatus.XPASSED,
}


class LogParser:
    def parse_log(self, log_content: str) -> list[LogEntry]:
        entries: list[LogEntry] = []
        for line in log_content.splitlines():
            if not line.strip():
                continue
            match = SUFFIX_RESULT.search(line) or LEVEL.search(line) or PREFIX_RESULT.search(line)
            node_match = match or NODEID.search(line)
            nodeid = node_match.group("node").strip() if node_match else None
            entries.append(
                LogEntry(
                    level=match.group("status") if match else "UNKNOWN",
                    message=line,
                    raw_line=line,
                    test_name=nodeid,
                    file_path=nodeid.split("::")[0] if nodeid else None,
                )
            )
        return entries

    def parse_log_file(self, file_path: Path) -> list[LogEntry]:
        return self.parse_log(file_path.read_text(encoding="utf-8"))


class LogAnalyzer:
    def __init__(self) -> None:
        self.parser = LogParser()

    def analyze_log(self, log_content: str) -> list[LogAnomaly]:
        entries = self.parser.parse_log(log_content)
        result: list[LogAnomaly] = []
        for idx, entry in enumerate(entries):
            for name, (regex, category, severity, confidence) in LOG_RULES.items():
                if re.search(regex, entry.message):
                    result.append(
                        LogAnomaly(
                            anomaly_type=name,
                            category=category,
                            severity=severity,
                            description=f"Log indicator: {name}",
                            confidence=confidence,
                            log_entries=tuple(entries[max(0, idx - 2) : idx + 3]),
                            metadata={"test_name": entry.test_name, "file_path": entry.file_path},
                        )
                    )
        return result

    def analyze_log_file(self, file_path: Path) -> list[LogAnomaly]:
        return self.analyze_log(file_path.read_text(encoding="utf-8"))

    def analyze_multiple_runs(self, log_contents: list[str]) -> dict[str, list[LogAnomaly]]:
        hits: dict[str, list[LogAnomaly]] = defaultdict(list)
        runs: dict[str, set[int]] = defaultdict(set)
        for run, content in enumerate(log_contents):
            for anomaly in self.analyze_log(content):
                key = (
                    f"{anomaly.anomaly_type}:{anomaly.metadata.get('test_name') or 'unattributed'}"
                )
                hits[key].append(anomaly)
                runs[key].add(run)
        return {key: values for key, values in hits.items() if len(runs[key]) < len(log_contents)}

    def extract_test_results(self, log_content: str) -> list[TestRunResult]:
        return [
            TestRunResult(test_name=entry.test_name, status=STATUS_MAP[entry.level])
            for entry in self.parser.parse_log(log_content)
            if entry.test_name is not None and entry.level in STATUS_MAP
        ]
