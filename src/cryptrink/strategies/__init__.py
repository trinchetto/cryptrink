"""Trading strategies module for Cryptrink."""

from cryptrink.strategies.base import (
    BaseStrategy,
    Signal,
    SignalStrength,
    SignalType,
    StrategyContext,
)
from cryptrink.strategies.mean_reversion import (
    BollingerBandsStrategy,
    RsiMeanReversionStrategy,
)
from cryptrink.strategies.registry import (
    StrategyRegistry,
    create,
    get_registry,
    list_strategies,
    register,
    unregister,
)
from cryptrink.strategies.trend_following import SmaCrossoverStrategy

__all__ = [  # noqa: RUF022 - grouped by category for clarity
    # Base classes
    "BaseStrategy",
    "Signal",
    "SignalStrength",
    "SignalType",
    "StrategyContext",
    # Concrete strategies
    "SmaCrossoverStrategy",
    "RsiMeanReversionStrategy",
    "BollingerBandsStrategy",
    # Registry
    "StrategyRegistry",
    "register",
    "unregister",
    "create",
    "list_strategies",
    "get_registry",
]
