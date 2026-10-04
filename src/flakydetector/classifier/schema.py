"""Feature order AND semantics are versioned. Legacy demo models are incompatible."""

from __future__ import annotations

import hashlib
import json

FEATURE_SCHEMA_VERSION = "2.1.0"
FEATURE_NAMES: tuple[str, ...] = (
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
    "log_timeout",
    "log_connection_error",
    "log_port_in_use",
    "log_race_condition",
    "log_resource_leak",
    "log_database_error",
    "log_flaky_retry",
    "log_total_anomalies",
    "log_max_confidence",
    "category_async_race_condition",
    "category_timing_dependency",
    "category_global_state",
    "category_network_dependency",
    "category_non_deterministic_order",
    "category_resource_leak",
    "category_concurrent_access",
    "category_floating_point",
    "category_datetime_dependency",
    "ast_to_log_ratio",
    "high_confidence_pattern_count",
    "pattern_diversity",
    "has_session_or_module_fixture",
    "has_yield_in_fixture",
    "fixture_returns_mutable",
    "fixture_has_autouse",
    "test_uses_fixtures",
)
SCHEMA_HASH = hashlib.sha256(
    json.dumps([FEATURE_SCHEMA_VERSION, FEATURE_NAMES], separators=(",", ":")).encode()
).hexdigest()
