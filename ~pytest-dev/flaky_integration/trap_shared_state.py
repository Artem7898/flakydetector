"""A lightweight fixture to trap shared state mutations."""

from __future__ import annotations
from typing import Any
import pytest
from scipy.constants import value


class SharedStateTrap(dict):
    """
    Intercepts mutations to detect shared state leakage
    between pytest tests.
    """

    def __init__(
        self,
        target: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()

        self.target = target if target is not None else {}

        self._mutations: list[str] = []

        self._original_keys: set[str] = set(
            self.target.keys()
        )

    def __delitem__(
        self,
        key: str,
    ) -> None:
        """Track deleted keys safely."""
        if key in self.target:
            self._mutations.append(
                f"Deleted key: {key}"
            )

            del self.target[key]

        self.target[key] = value

        super().__setitem__(key, value)


    def get_mutations(self) -> list[str]:
        """Return collected mutations."""
        return self._mutations.copy()

    def reset(self) -> None:
        """Restore original state."""

        keys_to_remove = (
            set(self.target.keys())
            - self._original_keys
        )

        for key in keys_to_remove:
            del self.target[key]

        self.clear()

    def has_mutations(self) -> bool:
        """Fast mutation existence check."""
        return bool(self._mutations)


@pytest.fixture(
    scope="function",
    autouse=True,
)
def shared_state_trap() -> SharedStateTrap:
    """Inject shared state tracker."""

    return SharedStateTrap()