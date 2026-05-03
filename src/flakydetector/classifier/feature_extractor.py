"""Feature extraction from AST patterns and log anomalies for ML classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from flakydetector.analyzer.ast_analyzer import ASTAnalyzer
from flakydetector.analyzer.log_analyzer import LogAnalyzer
from flakydetector.models.domain import (
    ASTPattern,
    FlakyCategory,
    LogAnomaly,
)

# Feature names for model interpretability
FEATURE_NAMES: list[str] = [
    # AST-based features
    "ast_async_sleep",
    "ast_concurrent_tasks",
    "ast_time_sleep",
    "ast_global_mutation",
    "ast_network_call",
    "ast_dict_iteration",
    "ast_set_in_assertion",
    "ast_file_without_context",
    "ast_datetime_now",
    "ast_float_equality",
    "ast_float_comparison",
    "ast_total_patterns",
    "ast_max_confidence",
    "ast_avg_confidence",
    "ast_high_severity_count",
    "ast_critical_severity_count",

    # Log-based features
    "log_timeout",
    "log_connection_error",
    "log_port_in_use",
    "log_race_condition",
    "log_resource_leak",
    "log_database_error",
    "log_flaky_retry",
    "log_total_anomalies",
    "log_max_confidence",

    # Category indicators
    "category_async_race_condition",
    "category_timing_dependency",
    "category_global_state",
    "category_network_dependency",
    "category_non_deterministic_order",
    "category_resource_leak",
    "category_concurrent_access",
    "category_floating_point",
    "category_datetime_dependency",

    # Derived features
    "ast_to_log_ratio",
    "high_confidence_pattern_count",
    "pattern_diversity",
]


@dataclass(slots=True)
class TestFeatures:
    """Extracted features for a single test."""

    test_name: str
    file_path: str
    features: NDArray[np.float64]
    feature_dict: dict[str, float]
    ast_patterns: list[ASTPattern]
    log_anomalies: list[LogAnomaly]


class FeatureExtractor:
    """Extract ML features from AST patterns and log anomalies."""

    # Mapping from pattern types to feature indices
    AST_PATTERN_MAP: dict[str, int] = {
        "async_sleep": 0,
        "concurrent_tasks": 1,
        "time_sleep": 2,
        "global_mutation": 3,
        "network_call": 4,
        "dict_iteration": 5,
        "set_in_assertion": 6,
        "file_without_context": 7,
        "datetime_now": 8,
        "float_equality": 9,
        "float_comparison": 10,
    }

    LOG_ANOMALY_MAP: dict[str, int] = {
        "timeout": 16,
        "connection_error": 17,
        "port_in_use": 18,
        "race_condition": 19,
        "resource_leak": 20,
        "database_error": 21,
        "flaky_retry": 22,
    }

    CATEGORY_MAP: dict[FlakyCategory, int] = {
        FlakyCategory.ASYNC_RACE_CONDITION: 25,
        FlakyCategory.TIMING_DEPENDENCY: 26,
        FlakyCategory.GLOBAL_STATE: 27,
        FlakyCategory.NETWORK_DEPENDENCY: 28,
        FlakyCategory.NON_DETERMINISTIC_ORDER: 29,
        FlakyCategory.RESOURCE_LEAK: 30,
        FlakyCategory.CONCURRENT_ACCESS: 31,
        FlakyCategory.FLOATING_POINT: 32,
        FlakyCategory.DATE_TIME_DEPENDENCY: 33,
    }

    def __init__(
            self,
            ast_analyzer: ASTAnalyzer | None = None,
            log_analyzer: LogAnalyzer | None = None,
    ) -> None:
        self._ast_analyzer = ast_analyzer or ASTAnalyzer()
        self._log_analyzer = log_analyzer or LogAnalyzer()
        self._n_features = len(FEATURE_NAMES)

    def extract_from_patterns(
            self,
            test_name: str,
            file_path: str,
            ast_patterns: list[ASTPattern],
            log_anomalies: list[LogAnomaly],
    ) -> TestFeatures:
        """Extract features from pre-analyzed patterns."""
        features = np.zeros(self._n_features, dtype=np.float64)
        feature_dict = {name: 0.0 for name in FEATURE_NAMES}

        # AST pattern counts
        for pattern in ast_patterns:
            idx = self.AST_PATTERN_MAP.get(pattern.pattern_type)
            if idx is not None:
                features[idx] += 1
                feature_dict[FEATURE_NAMES[idx]] += 1

            # Track categories
            cat_idx = self.CATEGORY_MAP.get(pattern.category)
            if cat_idx is not None:
                features[cat_idx] += 1
                feature_dict[FEATURE_NAMES[cat_idx]] += 1

        # AST summary features
        features[11] = len(ast_patterns)
        feature_dict["ast_total_patterns"] = len(ast_patterns)

        if ast_patterns:
            confidences = [p.confidence for p in ast_patterns]
            features[12] = max(confidences)
            features[13] = np.mean(confidences)
            feature_dict["ast_max_confidence"] = features[12]
            feature_dict["ast_avg_confidence"] = features[13]

            features[14] = sum(1 for p in ast_patterns if p.severity.value == "high")
            features[15] = sum(1 for p in ast_patterns if p.severity.value == "critical")
            feature_dict["ast_high_severity_count"] = features[14]
            feature_dict["ast_critical_severity_count"] = features[15]

        # Log anomaly counts
        for anomaly in log_anomalies:
            idx = self.LOG_ANOMALY_MAP.get(anomaly.anomaly_type)
            if idx is not None:
                features[idx] += 1
                feature_dict[FEATURE_NAMES[idx]] += 1

        # Log summary features
        features[23] = len(log_anomalies)
        feature_dict["log_total_anomalies"] = len(log_anomalies)

        if log_anomalies:
            confidences = [a.confidence for a in log_anomalies]
            features[24] = max(confidences)
            feature_dict["log_max_confidence"] = features[24]

        # Derived features
        ast_total = features[11]
        log_total = features[23]
        features[34] = ast_total / (log_total + 1)
        feature_dict["ast_to_log_ratio"] = features[34]

        all_confidences = [p.confidence for p in ast_patterns] + [a.confidence for a in log_anomalies]
        features[35] = sum(1 for c in all_confidences if c >= 0.8)
        feature_dict["high_confidence_pattern_count"] = features[35]

        # Pattern diversity (unique categories)
        categories = set(p.category for p in ast_patterns)
        features[36] = len(categories)
        feature_dict["pattern_diversity"] = features[36]

        return TestFeatures(
            test_name=test_name,
            file_path=file_path,
            features=features,
            feature_dict=feature_dict,
            ast_patterns=ast_patterns,
            log_anomalies=log_anomalies,
        )

    def extract_batch(
            self,
            items: list[tuple[str, str, list[ASTPattern], list[LogAnomaly]]],
    ) -> tuple[NDArray[np.float64], list[TestFeatures]]:
        """Extract features for a batch of tests."""
        results: list[TestFeatures] = []
        feature_matrix = np.zeros((len(items), self._n_features), dtype=np.float64)

        for i, (test_name, file_path, ast_patterns, log_anomalies) in enumerate(items):
            test_features = self.extract_from_patterns(
                test_name, file_path, ast_patterns, log_anomalies
            )
            results.append(test_features)
            feature_matrix[i] = test_features.features

        return feature_matrix, results

    def get_feature_importance_compatible_names(self) -> list[str]:
        """Get feature names compatible with CatBoost feature importances."""
        return FEATURE_NAMES.copy()