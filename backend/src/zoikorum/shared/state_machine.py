"""Explicit state machines (Handbook ch. 8). Backend enforcement is mandatory."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from zoikorum.shared.errors import InvalidStateTransition


class StateMachine:
    def __init__(self, aggregate: str, transitions: Mapping[str, Iterable[str]]):
        self.aggregate = aggregate
        self._t = {k: frozenset(v) for k, v in transitions.items()}
        unknown = {s for targets in self._t.values() for s in targets} - set(self._t)
        if unknown:
            raise ValueError(f"{aggregate}: targets without a declared state: {unknown}")

    @property
    def states(self) -> frozenset[str]:
        return frozenset(self._t)

    def can(self, from_state: str, to_state: str) -> bool:
        return to_state in self._t.get(from_state, frozenset())

    def assert_can(self, from_state: str, to_state: str) -> None:
        if not self.can(from_state, to_state):
            raise InvalidStateTransition(self.aggregate, from_state, to_state)

    def is_terminal(self, state: str) -> bool:
        return not self._t.get(state)
