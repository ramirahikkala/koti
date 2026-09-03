from __future__ import annotations

from typing import Any

import pytest

from koti.heating.settings import Settings


@pytest.fixture(autouse=True)
def _ignore_repo_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests from picking up the developer's real .env (HEALTHCHECK_URL etc.)."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for var in ("HEALTHCHECK_URL", "DRY_RUN", "OUTDOOR_TEMP_TOPIC"):
        monkeypatch.delenv(var, raising=False)


class FakeBus:
    """Stand-in for koti.heating.publish.MqttBus."""

    def __init__(
        self, values: dict[str, float] | None = None, numbers: dict[str, float] | None = None
    ) -> None:
        self.values: dict[str, float] = values or {}
        self.numbers: dict[str, float] = numbers or {}
        self.switch_state: dict[str, bool] = {}  # keyed by "<prefix>/<component>"
        self.registered_numbers: list[str] = []
        self.publish_calls: list[tuple[Any, Any, Any]] = []
        self.watched: list[str] = []
        self.switch_calls: list[tuple[str, bool, str]] = []
        self.raw_publishes: list[tuple[str, str | float]] = []
        self.publish_raw_ok = True

    # ---- subscribe / read
    def watch(self, topic: str | None) -> None:
        if topic:
            self.watched.append(topic)

    def watch_switch(self, prefix: str, component: str = "switch:0") -> None:
        self.watched.append(f"{prefix}/status/{component}")

    def get_float(self, topic: str | None, *, max_age: Any = None) -> float | None:
        if not topic:
            return None
        v = self.values.get(topic)
        return None if v is None else float(v)

    def register_number(self, object_id: str, name: str, *, default: float, **_: Any) -> None:
        self.registered_numbers.append(object_id)
        self.numbers.setdefault(object_id, default)

    def number_value(self, object_id: str) -> float:
        return self.numbers[object_id]

    # ---- actuate
    def publish_raw(self, topic: str, payload: str | float, *, retain: bool = False) -> bool:
        self.raw_publishes.append((topic, payload))
        return self.publish_raw_ok

    def set_switch(self, prefix: str, on: bool, *, component: str = "switch:0") -> bool:
        self.switch_calls.append((prefix, on, component))
        self.switch_state[f"{prefix}/{component}"] = on
        return True

    def switch_output(self, prefix: str, component: str = "switch:0") -> bool | None:
        return self.switch_state.get(f"{prefix}/{component}")

    # ---- publish
    def publish(self, ctx: Any, rooms: Any, boiler: Any, *, price_avg: Any, price_avg_ex_top: Any):
        self.publish_calls.append((ctx, rooms, boiler))

    def connect(self) -> None: ...

    def close(self) -> None: ...


@pytest.fixture
def fake_bus() -> FakeBus:
    return FakeBus()
