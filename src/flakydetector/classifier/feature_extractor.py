"""Stdlib feature extraction: every named dimension has an explicit definition."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

from flakydetector.classifier.schema import FEATURE_NAMES
from flakydetector.models.domain import ASTPattern, FixtureInfo, LogAnomaly
from flakydetector.models.domain import FlakyCategory as C
from flakydetector.models.domain import FlakySeverity as S

CATEGORY_FEATURE = {
    C.ASYNC_RACE_CONDITION: "category_async_race_condition",
    C.TIMING_DEPENDENCY: "category_timing_dependency",
    C.GLOBAL_STATE: "category_global_state",
    C.NETWORK_DEPENDENCY: "category_network_dependency",
    C.NON_DETERMINISTIC_ORDER: "category_non_deterministic_order",
    C.RESOURCE_LEAK: "category_resource_leak",
    C.CONCURRENT_ACCESS: "category_concurrent_access",
    C.FLOATING_POINT: "category_floating_point",
    C.DATE_TIME_DEPENDENCY: "category_datetime_dependency",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class TestFeatures:
    test_name: str
    file_path: str
    features: tuple[float, ...]
    feature_dict: dict[str, float]
    ast_patterns: tuple[ASTPattern, ...]
    log_anomalies: tuple[LogAnomaly, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureInput:
    test_name: str
    file_path: str
    ast_patterns: tuple[ASTPattern, ...] = ()
    log_anomalies: tuple[LogAnomaly, ...] = ()
    fixtures: tuple[FixtureInfo, ...] = ()


class FeatureExtractor:
    def extract_from_patterns(
        self,
        test_name: str,
        file_path: str,
        ast_patterns: Sequence[ASTPattern],
        log_anomalies: Sequence[LogAnomaly],
        fixtures: Sequence[FixtureInfo] = (),
    ) -> TestFeatures:
        counts = Counter(p.pattern_type for p in ast_patterns)
        logs = Counter(p.anomaly_type for p in log_anomalies)
        values = dict.fromkeys(FEATURE_NAMES, 0.0)
        for name in FEATURE_NAMES[:11]:
            values[name] = float(counts[name.removeprefix("ast_")])
        for name in FEATURE_NAMES[16:23]:
            values[name] = float(logs[name.removeprefix("log_")])
        values.update(
            ast_total_patterns=float(len(ast_patterns)),
            ast_max_confidence=max((p.confidence for p in ast_patterns), default=0.0),
            ast_avg_confidence=fmean(p.confidence for p in ast_patterns) if ast_patterns else 0.0,
            ast_high_severity_count=float(sum(p.severity == S.HIGH for p in ast_patterns)),
            ast_critical_severity_count=float(sum(p.severity == S.CRITICAL for p in ast_patterns)),
            log_total_anomalies=float(len(log_anomalies)),
            log_max_confidence=max((p.confidence for p in log_anomalies), default=0.0),
        )
        evidence = [*ast_patterns, *log_anomalies]
        for item in evidence:
            feature = CATEGORY_FEATURE.get(item.category)
            if feature:
                values[feature] += 1.0
        values.update(
            ast_to_log_ratio=len(ast_patterns) / max(1, len(log_anomalies)),
            high_confidence_pattern_count=float(sum(p.confidence >= 0.8 for p in evidence)),
            pattern_diversity=float(len({p.category for p in evidence})),
            has_session_or_module_fixture=float(
                any(f.scope in {"session", "module"} for f in fixtures)
            ),
            has_yield_in_fixture=float(any(f.has_yield for f in fixtures)),
            fixture_returns_mutable=float(any(f.returns_mutable_literal for f in fixtures)),
            fixture_has_autouse=float(any(f.has_autouse for f in fixtures)),
            test_uses_fixtures=float(bool(fixtures)),
        )
        return TestFeatures(
            test_name=test_name,
            file_path=file_path,
            features=tuple(values[n] for n in FEATURE_NAMES),
            feature_dict=values,
            ast_patterns=tuple(ast_patterns),
            log_anomalies=tuple(log_anomalies),
        )

    def extract_batch(self, items: Sequence[FeatureInput]) -> tuple[tuple[float, ...], ...]:
        return tuple(
            self.extract_from_patterns(
                i.test_name, i.file_path, i.ast_patterns, i.log_anomalies, i.fixtures
            ).features
            for i in items
        )
