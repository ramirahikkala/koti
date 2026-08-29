"""Direct HTTP control of Shelly LAN devices.

The controller runs on the Hetzner VM, which has the Tailscale link into the home network,
so it can reach ``http://192.168.86.x`` directly. Used for the Shelly TRV fake-temperature
trick; relay control still goes through Home Assistant services.
"""

from __future__ import annotations

import time

import httpx
import structlog

log = structlog.get_logger(__name__)


def send_ext_temp(url_prefix: str, temp: float, *, timeout: float = 5.0, retries: int = 3) -> bool:
    """GET ``{url_prefix}{temp:.1f}`` (the Shelly TRV external-temperature endpoint).

    A few quick retries only - the 15-minute control cycle is the real retry loop.
    """
    url = f"{url_prefix}{temp:.1f}"
    delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            resp = httpx.get(url, timeout=timeout)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            log.warning("shelly.ext_temp_failed", url=url, attempt=attempt, error=str(exc))
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
    return False
