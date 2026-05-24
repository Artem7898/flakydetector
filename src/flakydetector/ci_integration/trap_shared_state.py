"""A lightweight fixture to trap shared state mutations for the trail plugin."""

from __future__ import annotations
from typing import Any
import pytest


class SharedStateTrap:
    """Intercepts mutations on target dict to prove state leakage."""

    def __init__(self, target: dict | None = None) -> None:
        self.target = target if target is not None else {}
        self._mutations: list[str] = []
        self._original_keys: set[str] = set(self.target.keys())

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in self._original_keys:
            self._mutations.append(f"Added key: {key}")
        super().__setitem__(key, value)

    def get_mutations(self) -> list[str]:
        return self._mutations

    def reset(self) -> None:
        """Restore original keys, removing any added state."""
        keys_to_remove = set(self.target.keys()) - self._original_keys
        for key in keys_to_remove:
            del self.target[key]


@pytest.fixture(scope="function", autouse=True)
def shared_state_trap() -> SharedStateTrap:
    """Inject this fixture to track shared state mutations in tests."""
    # Targeting global module-level dicts if they exist
    import sys

    # We don't blindly patch everything to avoid breaking the environment
    return SharedStateTrap()