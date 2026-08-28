"""Daily price summary stats published for dashboards.

In v1 these were computed client-side in the dashboard JS. Here they are computed once and
published as HA sensors.
"""

from __future__ import annotations


def average(prices: list[float]) -> float | None:
    return round(sum(prices) / len(prices), 2) if prices else None


def average_excluding_top_hours(prices: list[float], hours: float) -> float | None:
    """Mean price with the ``hours`` most expensive hours (``hours * 4`` quarters) removed."""
    if not prices:
        return None
    drop = min(int(hours * 4), len(prices))
    kept = sorted(prices)[: len(prices) - drop]
    return round(sum(kept) / len(kept), 2) if kept else None
