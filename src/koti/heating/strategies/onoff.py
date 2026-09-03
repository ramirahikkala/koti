"""On/off room controller: heat while temp < base setpoint + price shift."""

from __future__ import annotations

import structlog

from koti.heating.logic.price_adjust import setpoint_temperature
from koti.heating.models import ControlContext, RoomConfig, RoomControl, RoomResult
from koti.heating.publish import MqttBus
from koti.heating.strategies.base import register

log = structlog.get_logger(__name__)


class OnOffStrategy:
    def apply(
        self, room: RoomConfig, ctx: ControlContext, bus: MqttBus, *, dry_run: bool
    ) -> RoomResult:
        assert room.base_temp is not None  # guaranteed by RoomConfig validation
        base = bus.number_value(f"heating_{room.id}_base_temp")

        setpoint, adjustment = setpoint_temperature(
            ctx.current_price,
            base,
            low_threshold=room.price_low_threshold,
            max_variation=room.temp_variation,
        )

        temp = bus.get_float(room.temp_topic)
        if temp is None:
            return RoomResult(
                zone_id=room.id,
                control=RoomControl.ONOFF,
                heat_demand=False,
                adjustment=adjustment,
                setpoint=setpoint,
                detail=f"temp topic {room.temp_topic} unavailable - not actuating",
            )

        heat = temp < setpoint
        actuated = False
        assert room.switch_topic is not None  # guaranteed by RoomConfig validation
        if dry_run:
            log.info("onoff.dry_run", zone=room.id, would_set=room.switch_topic, on=heat)
        else:
            actuated = bus.set_switch(room.switch_topic, heat, component=room.switch_component)

        return RoomResult(
            zone_id=room.id,
            control=RoomControl.ONOFF,
            heat_demand=heat,
            adjustment=adjustment,
            setpoint=setpoint,
            raw_temp=temp,
            actuated=actuated,
            detail=(
                f"temp {temp:.2f} vs setpoint {setpoint:.2f} "
                f"(base {base:.2f}{adjustment:+.2f}) -> {'HEAT' if heat else 'idle'}"
            ),
        )


register(RoomControl.ONOFF, OnOffStrategy())
