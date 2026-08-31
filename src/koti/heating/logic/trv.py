"""Price-adjusted fake "current temperature" for Shelly TRV thermostats.

Ported verbatim from v1 ``src/background_tasks.calculate_price_adjusted_temperature``.

When electricity is expensive the TRV is told the room is warmer than it is, so it heats
less; when cheap, cooler, so it heats more. The adjustment is capped to +/- 1 degC.
"""

from __future__ import annotations

_PIVOT_PRICE = 5.0
_SLOPE = 5.0
_CAP = 1.0


def trv_fake_temperature(raw_temp: float, price: float) -> float:
    """Return the temperature to report to the TRV given the real sensor reading."""
    adjustment = (price - _PIVOT_PRICE) / _SLOPE
    adjustment = max(-_CAP, min(_CAP, adjustment))
    return raw_temp + adjustment
