"""Room control strategy protocol + registry."""

from __future__ import annotations

from typing import Protocol

from koti.ha.client import HAClient
from koti.heating.models import ControlContext, RoomConfig, RoomControl, RoomResult


class Strategy(Protocol):
    def apply(
        self, room: RoomConfig, ctx: ControlContext, ha: HAClient, *, dry_run: bool
    ) -> RoomResult: ...


_REGISTRY: dict[RoomControl, Strategy] = {}


def register(control: RoomControl, strategy: Strategy) -> None:
    _REGISTRY[control] = strategy


def strategy_for(control: RoomControl) -> Strategy:
    try:
        return _REGISTRY[control]
    except KeyError:  # pragma: no cover - guarded by config validation
        raise ValueError(f"no strategy registered for control {control!r}") from None
