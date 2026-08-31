"""Price -> room setpoint adjustment.

Ported verbatim from v1 ``src/temperature_logic.py``. The formula is a single linear
ramp with slope ``max_variation / low_threshold`` around ``low_threshold``, clamped to
``+/- max_variation``:

    price = 0                 -> +max_variation   (cheap / free)
    price = low_threshold     ->  0               (baseline)
    price = 2 * low_threshold -> -max_variation   (expensive)

Note: v1 also carried a ``PRICE_HIGH_THRESHOLD`` config value, but the formula never used
it. It is intentionally dropped here.
"""

from __future__ import annotations


def temperature_adjustment(price: float, *, low_threshold: float, max_variation: float) -> float:
    """Return the room setpoint adjustment in degC for the given price (c/kWh)."""
    adjustment = max_variation - (price * (max_variation / low_threshold))
    adjustment = max(-max_variation, min(max_variation, adjustment))
    return round(adjustment, 2)


def setpoint_temperature(
    price: float,
    base_temp: float,
    *,
    low_threshold: float,
    max_variation: float,
) -> tuple[float, float]:
    """Return ``(setpoint, adjustment)`` for the given price and base temperature."""
    adjustment = temperature_adjustment(
        price, low_threshold=low_threshold, max_variation=max_variation
    )
    return round(base_temp + adjustment, 2), adjustment
