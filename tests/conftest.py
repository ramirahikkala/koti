from __future__ import annotations

from typing import Any

import pytest


class FakeHA:
    """Stand-in for heating.ha.client.HAClient."""

    def __init__(self, states: dict[str, Any] | None = None) -> None:
        self.states = states or {}
        self.service_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.switch_calls: list[tuple[str, bool]] = []

    def get_state(self, entity_id: str) -> str | None:
        v = self.states.get(entity_id)
        return None if v is None else str(v)

    def get_state_float(self, entity_id: str) -> float | None:
        v = self.states.get(entity_id)
        return None if v is None else float(v)

    def call_service(self, domain: str, service: str, data: dict[str, Any]) -> bool:
        self.service_calls.append((domain, service, data))
        return True

    def set_switch(self, entity_id: str, on: bool, *, verify: bool = True) -> bool:
        self.switch_calls.append((entity_id, on))
        self.states[entity_id] = "on" if on else "off"
        return True


@pytest.fixture
def fake_ha() -> FakeHA:
    return FakeHA()
