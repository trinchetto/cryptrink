"""Shared runtime helpers for the CLI and the web app.

Both the Typer CLI in :mod:`cryptrink.cli` and the Gradio web app in
:mod:`cryptrink.web` need to register the built-in strategies and create an
async SQLAlchemy session factory. Centralising those helpers here keeps the
two entrypoints in lockstep and prevents the registry from drifting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cryptrink.strategies import registry as strategy_registry
from cryptrink.strategies.mean_reversion import (
    BollingerBandsStrategy,
    RsiMeanReversionStrategy,
)
from cryptrink.strategies.trend_following import SmaCrossoverStrategy

if TYPE_CHECKING:
    from cryptrink.strategies.base import BaseStrategy

BUILTIN_STRATEGIES: dict[str, type[BaseStrategy]] = {
    "sma_crossover": SmaCrossoverStrategy,
    "rsi_mean_reversion": RsiMeanReversionStrategy,
    "bollinger_bands": BollingerBandsStrategy,
}


def ensure_builtins_registered() -> None:
    """Register built-in strategies in the global registry if not present.

    Idempotent: safe to call from multiple entrypoints during a single process
    lifetime.
    """
    registry = strategy_registry.get_registry()
    for name, factory in BUILTIN_STRATEGIES.items():
        if not registry.is_registered(name):
            registry.register(name, factory)


def resolve_strategy(name: str) -> BaseStrategy:
    """Resolve a strategy name to an instance using default parameters.

    Args:
        name: Registered strategy name.

    Returns:
        Instantiated :class:`BaseStrategy`.

    Raises:
        KeyError: If the strategy is not registered. Callers are responsible
            for translating this into their own UX (typer.Exit, gr.Error, …).
    """
    ensure_builtins_registered()
    return strategy_registry.create(name)


def build_session_factory(db_url: str) -> async_sessionmaker[AsyncSession]:
    """Create an async SQLAlchemy session factory for the given URL."""
    engine = create_async_engine(db_url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def list_builtin_strategy_names() -> list[str]:
    """Return the sorted list of built-in strategy names."""
    return sorted(BUILTIN_STRATEGIES.keys())
