"""Room control strategies. Importing this package registers all built-in strategies."""

from koti.heating.strategies import onoff, trv  # noqa: F401  (import for side-effect registration)
from koti.heating.strategies.base import Strategy, strategy_for

__all__ = ["Strategy", "strategy_for"]
