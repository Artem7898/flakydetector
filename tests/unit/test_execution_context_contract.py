"""F03 fail-closed boundaries and sensitive-option handling, independent of plugins."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from flakydetector.pytest_flaky_trail.context import execution_snapshot, hash_value, normalized


class Config:
    def __init__(self, *, options=None, ini=None):
        self.option = SimpleNamespace(**(options or {}))
        self.inicfg = ini or {}
        self.pluginmanager = SimpleNamespace(list_plugin_distinfo=lambda: [])

    def getini(self, name):
        if name not in self.inicfg:
            raise ValueError("unknown optional setting")
        return self.inicfg[name]


@pytest.mark.parametrize("value,expected", [
    (None, None), (True, True), (17, 17), (0.25, 0.25), ("strict", "strict"),
    (Path("tests/test_a.py"), "tests/test_a.py"),
    ({"b": [2, 1], "a": (True, None)}, {"b": [2, 1], "a": [True, None]}),
    ({3, 1, 2}, [1, 2, 3]), (frozenset({"b", "a"}), ["a", "b"]),
])
def test_supported_values_have_deterministic_json(value, expected):
    assert normalized(value) == expected
    assert hash_value(value) == hash_value(expected)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), {1: "not a string key"}, object()])
def test_unknown_or_nonfinite_option_cannot_be_hashed_as_comparable(value):
    with pytest.raises(ValueError):
        normalized(value)


def test_unserializable_option_blocks_automatic_comparability():
    snapshot = execution_snapshot(Config(options={"plugin_state": object()}), ["test_a.py::test_a"])
    assert snapshot["comparable_under_recorded_context"] is False
    assert snapshot["unavailable_keys"] == ["option:plugin_state"]


def test_unknown_configured_ini_is_not_silently_ignored():
    class Unknown(Config):
        def getini(self, name):
            raise ValueError("plugin did not register this setting")

    snapshot = execution_snapshot(Unknown(ini={"missing_plugin_option": "value"}), [])
    assert snapshot["comparable_under_recorded_context"] is False
    assert "ini:missing_plugin_option" in snapshot["unavailable_keys"]


def test_unserializable_ini_blocks_automatic_comparability():
    snapshot = execution_snapshot(Config(ini={"custom": object()}), [])
    assert snapshot["comparable_under_recorded_context"] is False
    assert snapshot["unavailable_keys"] == ["ini:custom"]


def test_effective_cli_secrets_are_hashed_not_exported():
    secret = "private-canary-value-for-unit-test"
    snapshot = execution_snapshot(Config(options={"service_token": secret}), [])
    assert snapshot["comparable_under_recorded_context"] is True
    assert secret not in json.dumps(snapshot)
    assert snapshot["effective_option_hashes"]["service_token"] == hash_value(secret)


def test_recorder_paths_are_not_comparison_keys_but_effective_options_are():
    one = execution_snapshot(Config(options={"flaky_trail_db": "one.db", "override_ini": ["filterwarnings=ignore"]}), ["test_a.py::test_a"])
    two = execution_snapshot(Config(options={"flaky_trail_db": "two.db", "override_ini": ["filterwarnings=ignore"]}), ["test_a.py::test_a"])
    changed = execution_snapshot(Config(options={"flaky_trail_db": "two.db", "override_ini": ["filterwarnings=error"]}), ["test_a.py::test_a"])
    assert one == two
    assert one != changed


def test_collection_order_is_preserved_not_sorted_away():
    first = execution_snapshot(Config(), ["test_a.py::test_a", "test_a.py::test_b"])
    second = execution_snapshot(Config(), ["test_a.py::test_b", "test_a.py::test_a"])
    assert first["collection_count"] == second["collection_count"] == 2
    assert first != second
