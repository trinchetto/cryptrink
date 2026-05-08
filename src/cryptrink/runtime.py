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
    from cryptrink.strategies.base import BaseStrategy, ParameterSpec

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


def resolve_strategy(name: str, **params: object) -> BaseStrategy:
    """Resolve a strategy name to an instance.

    Args:
        name: Registered strategy name.
        **params: Optional ``__init__`` keyword arguments forwarded to the
            registered factory. Omit to use the strategy's defaults.

    Returns:
        Instantiated :class:`BaseStrategy`.

    Raises:
        KeyError: If the strategy is not registered. Callers are responsible
            for translating this into their own UX (typer.Exit, gr.Error, …).
    """
    ensure_builtins_registered()
    return strategy_registry.create(name, **params)


def get_strategy_param_schema(name: str) -> list[ParameterSpec]:
    """Return the :class:`ParameterSpec` list for a registered strategy.

    Looks up the strategy class via :data:`BUILTIN_STRATEGIES` and delegates
    to its :meth:`BaseStrategy.param_schema` classmethod. For non-builtin
    strategies registered via factory functions we fall back to
    instantiating with defaults and reading the schema off the instance.
    """
    ensure_builtins_registered()
    cls = BUILTIN_STRATEGIES.get(name)
    if cls is not None:
        return cls.param_schema()
    # Fallback for externally-registered factories.
    instance = strategy_registry.create(name)
    return type(instance).param_schema()


def build_session_factory(db_url: str) -> async_sessionmaker[AsyncSession]:
    """Create an async SQLAlchemy session factory for the given URL."""
    engine = create_async_engine(db_url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def list_builtin_strategy_names() -> list[str]:
    """Return the sorted list of built-in strategy names."""
    return sorted(BUILTIN_STRATEGIES.keys())
