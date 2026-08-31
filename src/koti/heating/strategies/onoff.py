"""On/off room controller: heat while temp < base setpoint + price shift."""

from __future__ import annotations

import structlog

from koti.ha.client import HAClient
from koti.heating.logic.price_adjust import setpoint_temperature
from koti.heating.models import ControlContext, RoomConfig, RoomControl, RoomResult
from koti.heating.strategies.base import register

log = structlog.get_logger(__name__)


class OnOffStrategy:
    def apply(
        self, room: RoomConfig, ctx: ControlContext, ha: HAClient, *, dry_run: bool
    ) -> RoomResult:
        base = None
        if room.base_temp_entity:
            base = ha.get_state_float(room.base_temp_entity)
        if base is None:
            base = room.base_temp_fallback

        setpoint, adjustment = setpoint_temperature(
            ctx.current_price,
            base,
            low_threshold=room.price_low_threshold,
            max_variation=room.temp_variation,
        )

        temp = ha.get_state_float(room.temp_sensor)
        if temp is None:
            return RoomResult(
                zone_id=room.id,
                control=RoomControl.ONOFF,
                heat_demand=False,
                adjustment=adjustment,
                setpoint=setpoint,
                detail=f"temp sensor {room.temp_sensor} unavailable - not actuating",
            )

        heat = temp < setpoint
        actuated = False
        assert room.switch_entity is not None  # guaranteed by RoomConfig validation
        if dry_run:
            log.info("onoff.dry_run", zone=room.id, would_set=room.switch_entity, on=heat)
        else:
            actuated = ha.set_switch(room.switch_entity, heat)

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
