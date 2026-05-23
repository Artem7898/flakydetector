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
    # AST-based features (11)
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

    # AST summary features (5)
    "ast_total_patterns",
    "ast_max_confidence",
    "ast_avg_confidence",
    "ast_high_severity_count",
    "ast_critical_severity_count",

    # Log-based features (7)
    "log_timeout",
    "log_connection_error",
    "log_port_in_use",
    "log_race_condition",
    "log_resource_leak",
    "log_database_error",
    "log_flaky_retry",

    # Log summary features (2)
    "log_total_anomalies",
    "log_max_confidence",

    # Category indicators (9)
    "category_async_race_condition",
    "category_timing_dependency",
    "category_global_state",
    "category_network_dependency",
    "category_non_deterministic_order",
    "category_resource_leak",
    "category_concurrent_access",
    "category_floating_point",
    "category_datetime_dependency",

    # Derived features (3)
    "ast_to_log_ratio",
    "high_confidence_pattern_count",
    "pattern_diversity",

    # Fixture-based features - Sprint 1 (5)
    "has_session_or_module_fixture",
    "has_yield_in_fixture",
    "fixture_returns_mutable",
    "fixture_has_autouse",
    "test_uses_fixtures",
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
            fixtures: list[Any] | None = None,  # Добавили fixtures
    ) -> TestFeatures:
                # --- FIXTURE FEATURES (Sprint 1) ---
        fixtures = fixtures or []


        features = np.zeros(self._n_features, dtype=np.float64)
        feature_dict: dict[str, float] = {}

        features[37] = 1.0 if any(f.scope in ("module", "session") for f in fixtures) else 0.0
        feature_dict["has_session_or_module_fixture"] = features[37]

        features[38] = 1.0 if any(f.has_yield for f in fixtures) else 0.0
        feature_dict["has_yield_in_fixture"] = features[38]

        features[39] = 1.0 if any(f.returns_mutable_literal for f in fixtures) else 0.0
        feature_dict["fixture_returns_mutable"] = features[39]

        features[40] = 1.0 if any(f.has_autouse for f in fixtures) else 0.0
        feature_dict["fixture_has_autouse"] = features[40]

        # Проверяем, использует ли сам тест (не фикстура) аргументы-фикстуры
        # Это упрощенная проверка: если есть фикстуры в файле, считаем что тест их использует
        features[41] = sum(
            1.0 for f in fixtures
            if not f.has_yield and f.scope != "function"
                )
        feature_dict["test_uses_fixtures"] = features[41]
        feature_dict["test_uses_fixtures"] = features[41]

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