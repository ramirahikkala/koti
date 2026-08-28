"""Spot-Hinta electricity price API client.

Ported from v1 ``src/ha_client.py`` (get_current_price / get_daily_prices /
get_tomorrow_prices). Prices are returned in c/kWh including tax.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import structlog

log = structlog.get_logger(__name__)


class PriceClient:
    def __init__(
        self,
        justnow_url: str,
        forward_url: str,
        *,
        timezone: str = "Europe/Helsinki",
        timeout: float = 10.0,
        retries: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        self._justnow_url = justnow_url
        self._forward_url = forward_url
        self._tz = ZoneInfo(timezone)
        self._retries = retries
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def _get_json(self, url: str) -> object | None:
        delay = 1.0
        for attempt in range(1, self._retries + 1):
            try:
                resp = self._client.get(url)
                resp.raise_for_status()
                parsed: object = resp.json()
                return parsed
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("price.get_failed", url=url, attempt=attempt, error=str(exc))
                if attempt < self._retries:
                    time.sleep(delay)
                    delay *= 2
        return None

    def current_price(self) -> float | None:
        data = self._get_json(self._justnow_url)
        if not isinstance(data, dict):
            return None
        price = data.get("PriceWithTax")
        return round(price * 100, 4) if isinstance(price, (int, float)) else None

    def _prices_for(self, target: date) -> list[float]:
        data = self._get_json(self._forward_url)
        if not isinstance(data, list):
            return []
        out: list[float] = []
        for point in data:
            if not isinstance(point, dict):
                continue
            try:
                dt = datetime.fromisoformat(point["DateTime"])
            except (KeyError, ValueError):
                continue
            if dt.date() == target and isinstance(point.get("PriceWithTax"), (int, float)):
                out.append(round(point["PriceWithTax"] * 100, 4))
        return out

    def daily_prices(self) -> list[float]:
        return self._prices_for(datetime.now(self._tz).date())

    def tomorrow_prices(self) -> list[float] | None:
        prices = self._prices_for(datetime.now(self._tz).date() + timedelta(days=1))
        return prices if len(prices) >= 96 else None
