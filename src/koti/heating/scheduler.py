"""Process entry point: run the control cycle at :00/:15/:30/:45."""

from __future__ import annotations

import signal
import sys
import time

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from koti.common.logging_setup import configure
from koti.ha.price import PriceClient
from koti.heating.control import run_cycle, sync_numbers
from koti.heating.publish import MqttBus
from koti.heating.settings import Settings, load_settings
from koti.heating.zones import load_zones

log = structlog.get_logger(__name__)

_SETTLE_SECONDS = 3.0  # let retained + freshly-broadcast values land before the first cycle


def _connect_bus(bus: MqttBus, retries: int = 5) -> bool:
    delay = 2.0
    for attempt in range(1, retries + 1):
        try:
            bus.connect()
            return True
        except Exception:
            log.warning("mqtt.connect_failed", attempt=attempt)
            if attempt < retries:
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
    return False


def _register_bus_topics(bus: MqttBus, settings: Settings) -> None:
    bus.watch(settings.outdoor_temp_topic)
    try:
        cfg = load_zones(settings.zones_file)
    except Exception:
        log.exception("mqtt.zones_unreadable_at_startup")
        return
    for room in cfg.rooms:
        bus.watch(room.temp_topic)
        if room.switch_topic:
            bus.watch_switch(room.switch_topic, room.switch_component)
    if cfg.boiler is not None:
        bus.watch_switch(cfg.boiler.switch_topic, cfg.boiler.switch_component)
    # Declare the number entities now (not just in run_cycle) so their retained state lands
    # during the settle window and the first cycle uses the user's last value, not default.
    sync_numbers(cfg, bus)


def main() -> None:
    configure()
    settings = load_settings()

    prices = PriceClient(
        settings.spot_hinta_api_justnow,
        settings.spot_hinta_api_url,
        timezone=settings.timezone,
    )

    bus = MqttBus(settings)
    if _connect_bus(bus):
        _register_bus_topics(bus, settings)
        time.sleep(_SETTLE_SECONDS)
    else:
        log.error("mqtt.unavailable - cycles will run but sensor reads + actuation will fail")

    def cycle() -> None:
        try:
            run_cycle(settings, prices, bus)
        except Exception:
            log.exception("cycle.unhandled")

    scheduler = BlockingScheduler(timezone=settings.timezone)
    scheduler.add_job(
        cycle,
        CronTrigger(minute="0,15,30,45", timezone=settings.timezone),
        id="control",
        name="heating control cycle",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    def shutdown(*_: object) -> None:
        log.info("shutdown")
        scheduler.shutdown(wait=False)
        bus.close()
        prices.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    log.info("scheduler.start", timezone=settings.timezone, dry_run=settings.dry_run)
    cycle()  # run once at startup
    scheduler.start()


if __name__ == "__main__":
    main()
