"""CLI utility functions."""

import asyncio
from collections.abc import Coroutine
from decimal import Decimal
from typing import TypeVar

import typer
from rich.console import Console
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cryptrink.core.config import Settings
from cryptrink.data.feed import HistoricalDataFeed
from cryptrink.data.storage import Base, OHLCVRepository
from cryptrink.runtime import ensure_builtins_registered
from cryptrink.strategies import registry as strategy_registry
from cryptrink.strategies.base import BaseStrategy

T = TypeVar("T")

console = Console()


def run_async[T](coro: Coroutine[None, None, T]) -> T:
    """Run async coroutine from sync context.

    Args:
        coro: Async coroutine to execute.

    Returns:
        Result of the coroutine.

    Raises:
        Exception: Re-raises any exception from coroutine with user-friendly message.
    """
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/yellow]")
        raise SystemExit(0) from None
    except typer.Exit:
        # Commands raise typer.Exit themselves after printing their own
        # diagnostics; don't double-decorate it as an unhandled error.
        raise
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise


def create_session_factory(config: Settings) -> async_sessionmaker[AsyncSession]:
    """Create SQLAlchemy async session factory.

    Args:
        config: Application settings.

    Returns:
        Async session factory.
    """
    engine = create_async_engine(
        config.database.url,
        echo=config.database.echo,
    )

    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def init_db_schema(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Create every Cryptrink table if missing.

    Idempotent (``CREATE TABLE IF NOT EXISTS``). Run this once per command
    after :func:`create_session_factory` so a fresh sqlite file or HF Space
    boot doesn't crash with ``no such table`` on the first query.
    """
    # Import for side effect: registers Order/Position/Trade/EngineState
    # mappers against the shared ``Base.metadata`` so create_all() emits
    # every table, not just OHLCV.
    import cryptrink.execution.models  # noqa: F401

    db_engine = session_factory.kw["bind"]
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def load_strategy(strategy_name: str, **params: object) -> BaseStrategy:
    """Load strategy from registry.

    Built-in strategies are registered lazily on first call so the CLI works
    without needing a separate import-side-effect bootstrap step.

    Args:
        strategy_name: Name of strategy (e.g., "sma_crossover").
        **params: Strategy parameters.

    Returns:
        Instantiated strategy.

    Raises:
        ValueError: If strategy not found.
    """
    ensure_builtins_registered()
    try:
        return strategy_registry.create(strategy_name, **params)
    except KeyError:
        available = ", ".join(strategy_registry.list_strategies())
        msg = f"Strategy '{strategy_name}' not found. Available: {available}"
        raise ValueError(msg) from None


def create_data_feed(
    config: Settings,  # noqa: ARG001
    session_factory: async_sessionmaker[AsyncSession],
) -> HistoricalDataFeed:
    """Create historical data feed.

    Args:
        config: Application settings (reserved for future use).
        session_factory: Database session factory.

    Returns:
        HistoricalDataFeed instance.
    """
    repo = OHLCVRepository(session_factory)
    return HistoricalDataFeed(repo)


def format_currency(amount: Decimal) -> str:
    """Format decimal as currency.

    Args:
        amount: Amount to format.

    Returns:
        Formatted string (e.g., "€10,000.00").
    """
    return f"€{float(amount):,.2f}"


def format_percentage(value: Decimal, decimals: int = 2) -> str:
    """Format decimal as percentage.

    Args:
        value: Value to format (0.1 = 10%).
        decimals: Number of decimal places.

    Returns:
        Formatted string (e.g., "10.50%").
    """
    return f"{float(value) * 100:.{decimals}f}%"
