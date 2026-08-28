"""Shelly TRV controller: feed the thermostat a price-adjusted fake current temperature."""

from __future__ import annotations

import structlog

from heating.ha.client import HAClient
from heating.logic.trv import trv_fake_temperature
from heating.models import ControlContext, RoomConfig, RoomControl, RoomResult
from heating.strategies.base import register

log = structlog.get_logger(__name__)


class TrvStrategy:
    def apply(
        self, room: RoomConfig, ctx: ControlContext, ha: HAClient, *, dry_run: bool
    ) -> RoomResult:
        raw = ha.get_state_float(room.temp_sensor)
        if raw is None:
            return RoomResult(
                zone_id=room.id,
                control=RoomControl.TRV,
                heat_demand=False,
                adjustment=0.0,
                detail=f"temp sensor {room.temp_sensor} unavailable - not actuating",
            )

        trv_temp = round(trv_fake_temperature(raw, ctx.current_price), 1)
        adjustment = round(trv_temp - raw, 2)

        assert room.trv_ext_temp_service is not None  # guaranteed by RoomConfig validation
        domain, _, service = room.trv_ext_temp_service.partition(".")
        actuated = False
        if dry_run:
            log.info("trv.dry_run", zone=room.id, service=room.trv_ext_temp_service, temp=trv_temp)
        else:
            actuated = ha.call_service(domain, service, {"temp": trv_temp})

        return RoomResult(
            zone_id=room.id,
            control=RoomControl.TRV,
            heat_demand=trv_temp < raw,
            adjustment=adjustment,
            trv_temp=trv_temp,
            raw_temp=raw,
            actuated=actuated,
            detail=(
                f"raw {raw:.2f} -> reported {trv_temp:.1f} ({adjustment:+.2f}) "
                f"@ {ctx.current_price:.2f} c/kWh"
            ),
        )


register(RoomControl.TRV, TrvStrategy())
