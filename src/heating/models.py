"""Config and runtime data models.

Config models (loaded from ``zones.yaml``) are pydantic for validation. Runtime results are
plain dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class RoomControl(StrEnum):
    TRV = "trv"
    ONOFF = "onoff"


class RoomDefaults(BaseModel):
    model_config = {"extra": "forbid"}

    price_low_threshold: float = 10.0
    temp_variation: float = 0.5


class RoomConfig(BaseModel):
    model_config = {"extra": "forbid"}

    id: str
    control: RoomControl
    temp_sensor: str
    enabled: bool = True
    requests_boiler_heat: bool = False

    # onoff
    switch_entity: str | None = None
    base_temp_entity: str | None = None
    base_temp_fallback: float = 21.0

    # trv
    trv_ext_temp_service: str | None = None

    # per-room threshold overrides (filled from RoomDefaults at load time)
    price_low_threshold: float = 10.0
    temp_variation: float = 0.5

    @model_validator(mode="after")
    def _check_control_fields(self) -> RoomConfig:
        if self.control is RoomControl.ONOFF and not self.switch_entity:
            raise ValueError(f"room {self.id!r}: control 'onoff' requires 'switch_entity'")
        if self.control is RoomControl.TRV and not self.trv_ext_temp_service:
            raise ValueError(f"room {self.id!r}: control 'trv' requires 'trv_ext_temp_service'")
        return self


class BoilerConfig(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool = True
    switch_entity: str
    inverted: bool = True
    max_shutoff_hours: float = 6.0
    price_always_on_threshold: float = 5.0


class _RoomsSection(BaseModel):
    model_config = {"extra": "forbid"}

    defaults: RoomDefaults = Field(default_factory=RoomDefaults)
    items: list[RoomConfig] = Field(default_factory=list)


class ZonesFile(BaseModel):
    """Raw shape of ``zones.yaml``."""

    model_config = {"extra": "forbid"}

    boiler: BoilerConfig | None = None
    rooms: _RoomsSection = Field(default_factory=_RoomsSection)


@dataclass(frozen=True)
class ZonesConfig:
    """Validated config with room defaults merged into each room."""

    boiler: BoilerConfig | None
    rooms: list[RoomConfig]


# --------------------------------------------------------------------------- runtime


@dataclass(frozen=True)
class ControlContext:
    now: datetime
    current_price: float
    daily_prices: list[float]
    tomorrow_prices: list[float] | None
    outdoor_temp: float | None


@dataclass(frozen=True)
class RoomResult:
    zone_id: str
    control: RoomControl
    heat_demand: bool
    adjustment: float
    detail: str
    setpoint: float | None = None
    trv_temp: float | None = None
    raw_temp: float | None = None
    actuated: bool = False


@dataclass(frozen=True)
class BoilerDecision:
    should_run: bool
    reason: str
    rank: int
    forced: bool
    price: float
