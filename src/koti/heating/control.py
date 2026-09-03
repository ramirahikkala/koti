"""One control cycle: read -> compute -> actuate -> publish."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import structlog

from koti.common.healthcheck import ping
from koti.ha.price import PriceClient
from koti.heating.logic.boiler import boiler_should_run, price_rank
from koti.heating.logic.price_stats import average, average_excluding_top_hours
from koti.heating.models import BoilerDecision, ControlContext, RoomResult, ZonesConfig
from koti.heating.publish import MqttBus
from koti.heating.settings import Settings
from koti.heating.strategies import strategy_for
from koti.heating.zones import load_zones

log = structlog.get_logger(__name__)


def build_context(bus: MqttBus, prices: PriceClient, settings: Settings) -> ControlContext | None:
    current = prices.current_price()
    if current is None:
        log.error("cycle.no_price")
        return None
    outdoor = bus.get_float(settings.outdoor_temp_topic)
    return ControlContext(
        now=datetime.now(ZoneInfo(settings.timezone)),
        current_price=current,
        daily_prices=prices.daily_prices(),
        tomorrow_prices=prices.tomorrow_prices(),
        outdoor_temp=outdoor,
    )


def sync_numbers(cfg: ZonesConfig, bus: MqttBus) -> None:
    """(Re)declare the controller-owned base-setpoint number entities. Idempotent - keeps
    any value a user has already set, so it is safe to call every cycle (picks up rooms
    added to zones.yaml without a restart)."""
    for room in cfg.rooms:
        if room.base_temp is None:
            continue
        bus.register_number(
            f"heating_{room.id}_base_temp",
            f"{room.id} base setpoint",
            default=room.base_temp.default,
            min_value=room.base_temp.min,
            max_value=room.base_temp.max,
            step=room.base_temp.step,
        )


def _run_rooms(
    cfg: ZonesConfig, ctx: ControlContext, bus: MqttBus, dry_run: bool
) -> list[RoomResult]:
    results: list[RoomResult] = []
    for room in cfg.rooms:
        if not room.enabled:
            continue
        try:
            result = strategy_for(room.control).apply(room, ctx, bus, dry_run=dry_run)
        except Exception:
            log.exception("room.failed", zone=room.id)
            continue
        log.info("room.done", zone=room.id, detail=result.detail, heat_demand=result.heat_demand)
        results.append(result)
    return results


def _run_boiler(
    cfg: ZonesConfig, ctx: ControlContext, rooms: list[RoomResult], bus: MqttBus, dry_run: bool
) -> BoilerDecision | None:
    if cfg.boiler is None or not cfg.boiler.enabled:
        return None

    requesters = {r.id for r in cfg.rooms if r.requests_boiler_heat}
    forced = any(r.zone_id in requesters and r.heat_demand for r in rooms)

    should_run, reason = boiler_should_run(
        ctx.current_price,
        ctx.daily_prices,
        max_shutoff_hours=cfg.boiler.max_shutoff_hours,
        always_on_threshold=cfg.boiler.price_always_on_threshold,
    )
    if forced and not should_run:
        should_run = True
        reason = f"forced on by room demand (would otherwise block: {reason})"

    decision = BoilerDecision(
        should_run=should_run,
        reason=reason,
        rank=price_rank(ctx.current_price, ctx.daily_prices),
        forced=forced,
        price=ctx.current_price,
    )

    # inverted: switch ON blocks the boiler; non-inverted: switch ON runs it
    switch_on = (not should_run) if cfg.boiler.inverted else should_run
    if dry_run:
        log.info("boiler.dry_run", would_set=cfg.boiler.switch_topic, on=switch_on, reason=reason)
    else:
        bus.set_switch(cfg.boiler.switch_topic, switch_on, component=cfg.boiler.switch_component)
    log.info("boiler.done", should_run=should_run, forced=forced, rank=decision.rank, reason=reason)
    return decision


def run_cycle(settings: Settings, prices: PriceClient, bus: MqttBus) -> None:
    try:
        cfg = load_zones(settings.zones_file)
    except Exception:
        log.exception("cycle.bad_zones", path=settings.zones_file)
        ping(settings.healthcheck_url, success=False)
        return

    sync_numbers(cfg, bus)

    ctx = build_context(bus, prices, settings)
    if ctx is None:
        ping(settings.healthcheck_url, success=False)
        return

    log.info(
        "cycle.start",
        price=round(ctx.current_price, 2),
        daily_prices=len(ctx.daily_prices),
        dry_run=settings.dry_run,
    )

    rooms = _run_rooms(cfg, ctx, bus, settings.dry_run)
    boiler = _run_boiler(cfg, ctx, rooms, bus, settings.dry_run)

    try:
        bus.publish(
            ctx,
            rooms,
            boiler,
            price_avg=average(ctx.daily_prices),
            price_avg_ex_top=average_excluding_top_hours(
                ctx.daily_prices, settings.price_avg_exclude_top_hours
            ),
        )
    except Exception:
        log.exception("cycle.publish_failed")

    ping(settings.healthcheck_url, success=True)
    log.info(
        "cycle.done", rooms=len(rooms), boiler_run=None if boiler is None else boiler.should_run
    )
