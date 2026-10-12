"""Versioned rule catalog. IDs are never recycled and severity is not probability."""

from __future__ import annotations

from dataclasses import dataclass

RULESET_VERSION = "3.0.0"
FINGERPRINT_VERSION = "1"


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    title: str
    version: str = "1.0.0"
    limitation: str = (
        "A static pattern does not establish runtime execution, intermittent failure or causation."
    )


RULES: dict[str, Rule] = {
    "network_call": Rule("FD-NET-001", "External network boundary"),
    "network_client_call": Rule(
        "FD-NET-002", "Client transport is not controlled by a supported boundary"
    ),
    "time_sleep": Rule("FD-TIME-001", "Fixed time delay"),
    "datetime_now": Rule("FD-TIME-002", "Wall-clock dependency"),
    "async_sleep": Rule("FD-ASYNC-001", "Time-based async waiting"),
    "concurrent_tasks": Rule("FD-ASYNC-002", "Concurrent scheduling (advisory)"),
    "orphan_task": Rule("FD-ASYNC-003", "Task completion is not guaranteed"),
    "global_mutation": Rule("FD-STATE-001", "Module-level state mutation"),
    "shared_fixture_state": Rule("FD-FIXTURE-001", "Shared mutable fixture state"),
    "shared_database": Rule("FD-DB-001", "Shared database fixture without resolved reset"),
    "fixed_cache_key": Rule("FD-CACHE-001", "Fixed cache key written by a test"),
    "file_without_context": Rule("FD-FS-001", "File acquisition without a supported context"),
    "fixed_file_path": Rule("FD-FS-002", "Literal shared write path"),
    "cwd_mutation": Rule("FD-ENV-001", "Working directory mutation without resolved restore"),
    "environment_mutation": Rule("FD-ENV-002", "Environment mutation without resolved restore"),
    "process_environment": Rule("FD-ENV-003", "Process locale or timezone mutation"),
    "dict_iteration": Rule("FD-ORDER-001", "Known set iteration (legacy feature name)"),
    "set_in_assertion": Rule("FD-ORDER-002", "Ordered assertion from an unordered set"),
    "random_assertion": Rule("FD-RANDOM-001", "Assertion depends on an uncontrolled random draw"),
    "float_equality": Rule(
        "FD-PRECISION-001",
        "Exact floating-point assertion",
        limitation="A brittle assertion can fail deterministically; this is not evidence of a flake.",
    ),
    "high_complexity": Rule(
        "FD-MAINT-001",
        "High branch complexity",
        limitation="Maintainability signal, not a measurement of runtime reliability.",
    ),
    "background_worker": Rule("FD-CONCURRENCY-001", "Background worker without guaranteed join"),
    "fixed_sleep_polling": Rule("FD-POLL-001", "Polling relies on fixed sleep"),
}
