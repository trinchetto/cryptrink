"""Command-line interface for Cryptrink trading agent."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cryptrink import __version__
from cryptrink.core.config import ExecutionMode, Settings, load_config
from cryptrink.core.logging import setup_logging
from cryptrink.strategies import registry as strategy_registry
from cryptrink.strategies.mean_reversion import (
    BollingerBandsStrategy,
    RsiMeanReversionStrategy,
)
from cryptrink.strategies.trend_following import SmaCrossoverStrategy

if TYPE_CHECKING:
    from cryptrink.execution.base import BaseExecutor
    from cryptrink.strategies.base import BaseStrategy

app = typer.Typer(
    name="cryptrink",
    help="Crypto trading agent for Revolut X with backtesting and strategy support.",
    no_args_is_help=True,
)
console = Console()


_BUILTIN_STRATEGIES: dict[str, type[BaseStrategy]] = {
    "sma_crossover": SmaCrossoverStrategy,
    "rsi_mean_reversion": RsiMeanReversionStrategy,
    "bollinger_bands": BollingerBandsStrategy,
}


def _ensure_builtins_registered() -> None:
    """Register built-in strategies in the global registry if not already present."""
    for name, factory in _BUILTIN_STRATEGIES.items():
        if not strategy_registry.get_registry().is_registered(name):
            strategy_registry.register(name, factory)


def _build_strategy(name: str) -> BaseStrategy:
    """Resolve a strategy name to an instance using default parameters."""
    _ensure_builtins_registered()
    try:
        return strategy_registry.create(name)
    except KeyError:
        available = ", ".join(strategy_registry.list_strategies()) or "(none)"
        console.print(
            f"[red]Unknown strategy '{name}'.[/red] Available: {available}",
        )
        raise typer.Exit(code=1) from None


def _build_session_factory(db_url: str) -> async_sessionmaker[AsyncSession]:
    """Create an async SQLAlchemy session factory for the given URL."""
    engine = create_async_engine(db_url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"[bold blue]cryptrink[/bold blue] version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Cryptrink - Crypto trading agent for Revolut X."""
    pass


async def _run_async(
    config: Settings,
    mode: ExecutionMode,
    strategy_name: str,
    symbols: list[str],
) -> None:
    """Initialize the trading engine and report its state.

    A continuous trading loop is intentionally not started here: the per-symbol
    market-data feed and signal-generation wiring live in later phases. This
    routine boots the full engine stack (strategy, executor, risk, persistence)
    so the wiring is exercised end-to-end and the operator can confirm the
    configuration is valid.
    """
    from cryptrink.execution.engine import TradingEngine
    from cryptrink.execution.models import Position
    from cryptrink.execution.paper import PaperExecutor
    from cryptrink.execution.suggest import SuggestExecutor

    strategy = _build_strategy(strategy_name)

    executor: BaseExecutor
    if mode == ExecutionMode.PAPER:
        executor = PaperExecutor(initial_balance=Decimal("10000"))
    elif mode == ExecutionMode.SUGGEST:
        executor = SuggestExecutor()
    elif mode == ExecutionMode.LIVE:
        console.print(
            "[red]Live mode requires an authenticated Revolut X client, which is not "
            "yet wired into the run command. Use paper or suggest mode for now.[/red]"
        )
        raise typer.Exit(code=2)
    else:
        console.print(f"[red]Unsupported execution mode for run: {mode.value}[/red]")
        raise typer.Exit(code=2)

    session_factory = _build_session_factory(config.database.url)

    db_engine = session_factory.kw["bind"]
    async with db_engine.begin() as conn:
        await conn.run_sync(Position.metadata.create_all)

    engine = TradingEngine(
        strategy=strategy,
        executor=executor,
        session_factory=session_factory,
        initial_balance=Decimal("10000"),
        risk_settings=config.risk,
    )

    await engine.start()
    try:
        summary = await engine.get_performance_summary()
    finally:
        await engine.stop()
        await db_engine.dispose()

    table = Table(title="Engine state")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("engine_id", engine.engine_id)
    table.add_row("strategy", strategy.__class__.__name__)
    table.add_row("mode", executor.mode.value)
    table.add_row("symbols", ", ".join(symbols) if symbols else "(none configured)")
    table.add_row("initial_balance", f"{summary['initial_balance']:.2f}")
    table.add_row("current_balance", f"{summary['current_balance']:.2f}")
    table.add_row("open_positions", str(summary["open_positions_count"]))
    console.print(table)
    console.print(
        "[dim]Note: market-data feed and signal loop are not yet wired; "
        "run started and stopped without processing live candles.[/dim]"
    )


@app.command()
def run(
    config_path: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    mode: Annotated[
        ExecutionMode,
        typer.Option("--mode", "-m", help="Execution mode."),
    ] = ExecutionMode.PAPER,
    strategy: Annotated[
        str | None,
        typer.Option("--strategy", "-s", help="Strategy to run."),
    ] = None,
    symbol: Annotated[
        str | None,
        typer.Option("--symbol", help="Trading symbol (e.g., BTC-EUR)."),
    ] = None,
) -> None:
    """Run the trading agent."""
    setup_logging()
    config = load_config(config_path)
    strategy_name = strategy or config.default_strategy
    symbols = [symbol] if symbol else config.symbols

    console.print(
        Panel(
            f"[bold green]Starting Cryptrink[/bold green]\n\n"
            f"Mode: {mode.value}\n"
            f"Strategy: {strategy_name}\n"
            f"Symbol: {symbol or 'All configured symbols'}",
            title="Cryptrink Trading Agent",
            border_style="blue",
        )
    )

    asyncio.run(_run_async(config, mode, strategy_name, symbols))


async def _backtest_async(
    config: Settings,
    strategy_name: str,
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    initial_capital: Decimal,
) -> None:
    """Build a BacktestEngine over historical data and print the result."""
    from cryptrink.backtest.engine import BacktestEngine
    from cryptrink.data.feed import HistoricalDataFeed
    from cryptrink.data.storage import OHLCV as OHLCVModel
    from cryptrink.data.storage import OHLCVRepository
    from cryptrink.execution.models import Position

    strategy = _build_strategy(strategy_name)

    session_factory = _build_session_factory(config.database.url)
    db_engine = session_factory.kw["bind"]
    async with db_engine.begin() as conn:
        await conn.run_sync(OHLCVModel.metadata.create_all)
        await conn.run_sync(Position.metadata.create_all)
    repository = OHLCVRepository(session_factory)
    data_feed = HistoricalDataFeed(repository)

    engine = BacktestEngine(
        strategy=strategy,
        data_feed=data_feed,
        initial_balance=initial_capital,
        session_factory=session_factory,
        risk_settings=config.risk,
    )

    try:
        result = await engine.run(
            symbol=symbol,
            start_time=start_dt,
            end_time=end_dt,
        )
    except ValueError as exc:
        console.print(f"[red]Backtest failed: {exc}[/red]")
        console.print(
            "[dim]Tip: ensure historical OHLCV data has been loaded into "
            f"{config.database.url} for the requested symbol/timeframe.[/dim]"
        )
        raise typer.Exit(code=1) from exc
    finally:
        await db_engine.dispose()

    result.print_summary()


@app.command()
def backtest(
    strategy: Annotated[str, typer.Argument(help="Strategy to backtest.")],
    symbol: Annotated[str, typer.Argument(help="Trading symbol (e.g., BTC-EUR).")],
    start_date: Annotated[
        str,
        typer.Option("--start", "-s", help="Start date (YYYY-MM-DD)."),
    ] = "2024-01-01",
    end_date: Annotated[
        str | None,
        typer.Option("--end", "-e", help="End date (YYYY-MM-DD)."),
    ] = None,
    initial_capital: Annotated[
        float,
        typer.Option("--capital", help="Initial capital in EUR."),
    ] = 10000.0,
    config_path: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Run a backtest for a strategy."""
    setup_logging()
    config = load_config(config_path)

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
        end_dt = (
            datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
            if end_date
            else datetime.now(UTC)
        )
    except ValueError as exc:
        console.print(f"[red]Invalid date: {exc}[/red]")
        raise typer.Exit(code=2) from exc

    if end_dt <= start_dt:
        console.print("[red]--end must be after --start[/red]")
        raise typer.Exit(code=2)

    console.print(
        Panel(
            f"[bold cyan]Backtesting[/bold cyan]\n\n"
            f"Strategy: {strategy}\n"
            f"Symbol: {symbol}\n"
            f"Period: {start_date} to {end_date or 'now'}\n"
            f"Initial Capital: €{initial_capital:,.2f}",
            title="Backtest Configuration",
            border_style="cyan",
        )
    )

    asyncio.run(
        _backtest_async(
            config=config,
            strategy_name=strategy,
            symbol=symbol,
            start_dt=start_dt,
            end_dt=end_dt,
            initial_capital=Decimal(str(initial_capital)),
        )
    )


async def _suggest_async(
    config: Settings,
    strategy_name: str,
    symbol: str,
    output_format: str,
) -> None:
    """Generate a single trade suggestion from the latest stored candles."""
    from cryptrink.data.feed import HistoricalDataFeed
    from cryptrink.data.indicators import ohlcv_to_dataframe
    from cryptrink.data.storage import OHLCV as OHLCVModel
    from cryptrink.data.storage import OHLCVRepository
    from cryptrink.execution.base import ExecutionContext
    from cryptrink.execution.suggest import SuggestExecutor
    from cryptrink.strategies.base import StrategyContext

    strategy = _build_strategy(strategy_name)

    session_factory = _build_session_factory(config.database.url)
    db_engine = session_factory.kw["bind"]
    async with db_engine.begin() as conn:
        await conn.run_sync(OHLCVModel.metadata.create_all)
    repository = OHLCVRepository(session_factory)
    data_feed = HistoricalDataFeed(repository)

    try:
        candles = await data_feed.get_ohlcv(
            symbol=symbol,
            timeframe=strategy.timeframe,
            limit=max(strategy.required_history + 10, 100),
        )
    except Exception:
        await db_engine.dispose()
        raise

    if not candles:
        await db_engine.dispose()
        console.print(
            f"[red]No historical data for {symbol} {strategy.timeframe} in "
            f"{config.database.url}.[/red]"
        )
        console.print(
            "[dim]Tip: load OHLCV data into the database before requesting suggestions.[/dim]"
        )
        raise typer.Exit(code=1)

    ohlcv_df = ohlcv_to_dataframe(candles)
    current_price = Decimal(str(ohlcv_df.iloc[-1]["close"]))
    timestamp = (
        ohlcv_df.index[-1].to_pydatetime()
        if hasattr(ohlcv_df.index[-1], "to_pydatetime")
        else datetime.now(UTC)
    )
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    context = StrategyContext(
        symbol=symbol,
        current_price=current_price,
        timestamp=timestamp,
        ohlcv=ohlcv_df,
    )
    signal = strategy.generate_signal(context)

    executor = SuggestExecutor()
    exec_context = ExecutionContext(
        symbol=symbol,
        current_price=current_price,
        timestamp=timestamp,
        account_balance=Decimal("10000"),
        has_position=False,
        position_size=Decimal("0"),
    )
    result = await executor.execute_signal(signal, exec_context)
    await db_engine.dispose()

    payload: dict[str, object] = {
        "symbol": symbol,
        "strategy": strategy.name,
        "timestamp": timestamp.isoformat(),
        "signal_type": signal.signal_type.value,
        "signal_strength": signal.strength.value,
        "current_price": str(current_price),
        "suggestion": {
            "success": result.success,
            "message": result.message,
            "order_id": result.order_id,
            "order_side": result.order_side.value if result.order_side else None,
            "order_type": result.order_type.value if result.order_type else None,
            "quantity": str(result.quantity) if result.quantity is not None else None,
            "price": str(result.price) if result.price is not None else None,
        },
    }

    if output_format == "json":
        console.print_json(json.dumps(payload))
        return

    table = Table(title=f"Suggestion for {symbol} ({strategy.name})")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("timestamp", payload["timestamp"])  # type: ignore[arg-type]
    table.add_row("signal", f"{signal.signal_type.value} ({signal.strength.value})")
    table.add_row("current_price", str(current_price))
    suggestion = payload["suggestion"]
    assert isinstance(suggestion, dict)
    if suggestion["success"]:
        table.add_row("action", f"{suggestion['order_side']} {suggestion['order_type']}")
        table.add_row("quantity", str(suggestion["quantity"]))
        table.add_row("price", str(suggestion["price"]))
    else:
        table.add_row("action", "no trade")
    table.add_row("message", str(suggestion["message"]))
    console.print(table)


@app.command()
def suggest(
    strategy: Annotated[str, typer.Argument(help="Strategy to use for suggestions.")],
    symbol: Annotated[str, typer.Argument(help="Trading symbol (e.g., BTC-EUR).")],
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format (table, json)."),
    ] = "table",
    config_path: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Get trade suggestions without executing."""
    setup_logging()
    config = load_config(config_path)

    if output_format not in {"table", "json"}:
        console.print(f"[red]Unknown format '{output_format}'. Use 'table' or 'json'.[/red]")
        raise typer.Exit(code=2)

    console.print(
        Panel(
            f"[bold magenta]Trade Suggestions[/bold magenta]\n\n"
            f"Strategy: {strategy}\n"
            f"Symbol: {symbol}\n"
            f"Format: {output_format}",
            title="Suggestion Mode",
            border_style="magenta",
        )
    )

    asyncio.run(
        _suggest_async(
            config=config,
            strategy_name=strategy,
            symbol=symbol,
            output_format=output_format,
        )
    )


@app.command()
def status() -> None:
    """Show current trading status and positions."""
    console.print(
        Panel(
            "[bold]Trading Status[/bold]\n\nNo active trading session.",
            title="Status",
            border_style="green",
        )
    )


if __name__ == "__main__":
    app()
