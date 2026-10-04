"""Recorded comparison context, not a claim to capture every external dependency.

Use effective getini()/option values, including CLI overrides. Only value hashes
are stored: pytest plugins may put credentials in their configuration/options.
An unsupported value disables automatic labels instead of producing a guessed key.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest
from pydantic import JsonValue

from flakydetector.utils.provenance import PROVENANCE_VERSION

KNOWN_INI = {
    "filterwarnings", "addopts", "xfail_strict", "empty_parameter_set_mark",
    "python_files", "python_classes", "python_functions", "pythonpath", "testpaths",
    "asyncio_mode", "asyncio_default_fixture_loop_scope", "asyncio_default_test_loop_scope",
}
# Exclude ONLY recorder bookkeeping; all other CLI options are conservative split keys.
RECORDER_OPTIONS = {
    "flaky_trail", "flaky_trail_db", "flaky_trail_repo", "flaky_trail_revision", "flaky_trail_env",
}
ENV_KEYS = ("PYTHONHASHSEED", "PYTHONWARNINGS", "PYTEST_ADDOPTS", "TZ", "LANG", "LC_ALL")


def normalized(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not (-float("inf") < value < float("inf")):
            raise ValueError("nonfinite option")
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        if not all(isinstance(key, str) for key in mapping):
            raise ValueError("non-string option keys")
        return {str(key): normalized(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        return [normalized(item) for item in cast(Sequence[object], value)]
    if isinstance(value, (set, frozenset)):
        return sorted(
            (normalized(item) for item in cast(set[object], value)),
            key=lambda item: json.dumps(item, sort_keys=True),
        )
    raise ValueError("unsupported pytest configuration value")


def hash_value(value: object) -> str:
    payload = json.dumps(normalized(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def execution_snapshot(config: pytest.Config, order: list[str]) -> dict[str, JsonValue]:
    unavailable: list[JsonValue] = []
    ini: dict[str, JsonValue] = {}
    for name in sorted(KNOWN_INI | set(config.inicfg)):
        try:
            value: object = config.getini(name)
        except ValueError:
            if name in config.inicfg:
                unavailable.append(f"ini:{name}")
            continue  # An absent optional plugin has no registered default.
        try:
            ini[name] = hash_value(value)
        except ValueError:
            unavailable.append(f"ini:{name}")
    options: dict[str, JsonValue] = {}
    for name, value in sorted(cast(dict[str, object], vars(config.option)).items()):
        if name in RECORDER_OPTIONS:
            continue
        try:
            options[name] = hash_value(value)
        except ValueError:
            unavailable.append(f"option:{name}")
    return {
        "provenance_version": PROVENANCE_VERSION,
        "comparable_under_recorded_context": not unavailable,
        "unavailable_keys": unavailable,
        "effective_ini_hashes": ini,
        "effective_option_hashes": options,
        "environment_hashes": {key: hash_value(os.environ.get(key)) for key in ENV_KEYS},
        "interpreter_warning_options_hash": hash_value(sys.warnoptions),
        "loaded_plugin_versions_hash": hash_value(sorted(
            (dist.project_name, dist.version) for _, dist in config.pluginmanager.list_plugin_distinfo()
        )),
        "collection_order": list(order),
        "collection_count": len(order),
    }
