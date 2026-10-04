"""Explicit shallow mapping proxy. It never injects itself into pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass
from typing import TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass(frozen=True, slots=True)
class Mutation[K]:
    operation: str
    key: K


class SharedStateTrap(MutableMapping[K, V]):
    """Tracks top-level writes only. Nested object mutations are intentionally unsupported."""

    def __init__(self, target: MutableMapping[K, V] | None = None) -> None:
        self.target: MutableMapping[K, V] = {} if target is None else target
        self._baseline = dict(self.target)
        self._mutations: list[Mutation[K]] = []

    def __getitem__(self, key: K) -> V:
        return self.target[key]

    def __setitem__(self, key: K, value: V) -> None:
        self.target[key] = value
        self._mutations.append(Mutation("set", key))

    def __delitem__(self, key: K) -> None:
        del self.target[key]
        self._mutations.append(Mutation("delete", key))

    def __iter__(self) -> Iterator[K]:
        return iter(self.target)

    def __len__(self) -> int:
        return len(self.target)

    def get_mutations(self) -> tuple[Mutation[K], ...]:
        return tuple(self._mutations)

    def has_mutations(self) -> bool:
        return bool(self._mutations)

    def reset(self) -> None:
        self.target.clear()
        self.target.update(self._baseline)
        self._mutations.clear()
