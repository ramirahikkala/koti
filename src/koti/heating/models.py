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


class BaseTempConfig(BaseModel):
    """A controller-owned MQTT ``number`` entity - the room's adjustable base setpoint."""

    model_config = {"extra": "forbid"}

    default: float
    min: float = 15.0
    max: float = 25.0
    step: float = 0.5


class RoomConfig(BaseModel):
    model_config = {"extra": "forbid"}

    id: str
    control: RoomControl
    temp_topic: str  # MQTT state topic, e.g. koti/sensor/kylpyhuone/state
    enabled: bool = True
    requests_boiler_heat: bool = False

    # onoff - a Shelly relay on MQTT: <switch_topic>/command/<component> takes on|off,
    # <switch_topic>/status/<component> reports {"output": bool}, <switch_topic>/online is the LWT.
    switch_topic: str | None = None
    switch_component: str = "switch:0"
    base_temp: BaseTempConfig | None = None

    # trv - MQTT topic the Shelly TRV reads as its external temperature (payload = degC)
    trv_ext_temp_topic: str | None = None

    # per-room threshold overrides (filled from RoomDefaults at load time)
    price_low_threshold: float = 10.0
    temp_variation: float = 0.5

    @model_validator(mode="after")
    def _check_control_fields(self) -> RoomConfig:
        if self.control is RoomControl.ONOFF and not self.switch_topic:
            raise ValueError(f"room {self.id!r}: control 'onoff' requires 'switch_topic'")
        if self.control is RoomControl.ONOFF and self.base_temp is None:
            raise ValueError(f"room {self.id!r}: control 'onoff' requires 'base_temp'")
        if self.control is RoomControl.TRV and not self.trv_ext_temp_topic:
            raise ValueError(f"room {self.id!r}: control 'trv' requires 'trv_ext_temp_topic'")
        return self


class BoilerConfig(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool = True
    switch_topic: str  # Shelly relay MQTT prefix, e.g. shelly1minig3-5432045dd3f0
    switch_component: str = "switch:0"
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
