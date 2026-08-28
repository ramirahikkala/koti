"""Process entry point: run the control cycle at :00/:15/:30/:45."""

from __future__ import annotations

import signal
import sys

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from heating.control import run_cycle
from heating.ha.client import HAClient
from heating.ha.price import PriceClient
from heating.ha.publish import Publisher
from heating.logging_setup import configure
from heating.settings import load_settings

log = structlog.get_logger(__name__)


def main() -> None:
    configure()
    settings = load_settings()

    ha = HAClient(settings.ha_url, settings.ha_api_token)
    prices = PriceClient(
        settings.spot_hinta_api_justnow,
        settings.spot_hinta_api_url,
        timezone=settings.timezone,
    )

    publisher: Publisher | None = None
    try:
        publisher = Publisher(settings)
        publisher.connect()
    except Exception:
        log.exception("mqtt.connect_failed - continuing without publishing")
        publisher = None

    def cycle() -> None:
        try:
            run_cycle(settings, ha, prices, publisher)
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
        if publisher is not None:
            publisher.close()
        ha.close()
        prices.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    log.info("scheduler.start", timezone=settings.timezone, dry_run=settings.dry_run)
    cycle()  # run once at startup
    scheduler.start()


if __name__ == "__main__":
    main()
