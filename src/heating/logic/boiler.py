"""Boiler (level 1) on/off decision.

Ported from v1 ``src/temperature_logic.should_central_heating_run``, with the two config
values passed in explicitly instead of read from module globals.

Rule:
- price < ``always_on_threshold``            -> run (never block)
- else block only if the current quarter is among the ``max_shutoff_hours * 4`` most
  expensive quarters of the day
"""

from __future__ import annotations


def price_rank(current_price: float, daily_prices: list[float]) -> int:
    """1-based rank of ``current_price`` among the day's quarters (1 = most expensive)."""
    return sum(1 for p in daily_prices if p >= current_price)


def boiler_should_run(
    current_price: float,
    daily_prices: list[float],
    *,
    max_shutoff_hours: float,
    always_on_threshold: float,
) -> tuple[bool, str]:
    """Return ``(should_run, reason)`` for the boiler based on price ranking."""
    if current_price < always_on_threshold:
        return True, (
            f"Price {current_price:.2f} c/kWh < threshold "
            f"{always_on_threshold:.2f} c/kWh (always on)"
        )

    if not daily_prices:
        return True, "No price data available"

    max_shutoff_quarters = int(max_shutoff_hours * 4)
    sorted_prices = sorted(daily_prices, reverse=True)

    if max_shutoff_quarters < len(sorted_prices):
        shutoff_threshold = sorted_prices[max_shutoff_quarters - 1]
    else:
        shutoff_threshold = min(daily_prices)

    rank = price_rank(current_price, daily_prices)

    if rank <= max_shutoff_quarters and current_price >= shutoff_threshold:
        return False, (
            f"In top-{max_shutoff_quarters} expensive quarters "
            f"(rank ~{rank}, price {current_price:.2f} c/kWh)"
        )
    return True, (
        f"Not in top-{max_shutoff_quarters} expensive quarters "
        f"(price {current_price:.2f} c/kWh, threshold {shutoff_threshold:.2f} c/kWh)"
    )
