"""Command-line interface for Cryptrink trading agent."""

from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from cryptrink import __version__
from cryptrink.core.config import ExecutionMode, load_config
from cryptrink.core.logging import setup_logging

app = typer.Typer(
    name="cryptrink",
    help="Crypto trading agent for Revolut X with backtesting and strategy support.",
    no_args_is_help=True,
)
console = Console()


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
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", help="Enable interactive mode."),
    ] = False,
    params: Annotated[
        str | None,
        typer.Option("--params", help="Strategy parameters as JSON."),
    ] = None,
) -> None:
    """Run the trading agent."""
    import asyncio
    import json
    from decimal import Decimal

    from cryptrink.cli.utils import create_session_factory, load_strategy, run_async
    from cryptrink.execution.engine import TradingEngine
    from cryptrink.execution.paper import PaperExecutor
    from cryptrink.notifications.discord import DiscordNotifier

    setup_logging()
    config = load_config(config_path)

    # Override config with CLI args
    if mode:
        config.execution_mode = mode
    if strategy:
        config.default_strategy = strategy
    if symbol:
        config.symbols = [symbol]

    console.print(
        Panel(
            f"[bold green]Starting Cryptrink[/bold green]\n\n"
            f"Mode: {config.execution_mode.value}\n"
            f"Strategy: {config.default_strategy}\n"
            f"Symbols: {', '.join(config.symbols)}\n"
            f"Interactive: {'Yes' if interactive else 'No'}",
            title="Cryptrink Trading Agent",
            border_style="blue",
        )
    )

    # Validate mode
    if (
        config.execution_mode == ExecutionMode.LIVE
        and not config.revolutx.api_key.get_secret_value()
    ):
        console.print("[red]LIVE mode requires REVOLUTX_API_KEY[/red]")
        raise typer.Exit(1)

    # Parse parameters
    strategy_params = {}
    if params:
        try:
            strategy_params = json.loads(params)
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON in --params: {e}[/red]")
            raise typer.Exit(1) from e

    async def start_trading() -> None:
        # Load strategy
        try:
            strat = load_strategy(config.default_strategy, **strategy_params)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e

        # Create session factory
        session_factory = create_session_factory(config)

        # Create executor
        if config.execution_mode == ExecutionMode.PAPER:
            executor = PaperExecutor(initial_balance=Decimal("10000"))
        elif config.execution_mode == ExecutionMode.LIVE:
            console.print("[red]LIVE mode not yet implemented[/red]")
            raise typer.Exit(1)
        else:
            console.print(f"[red]Invalid mode for run command: {config.execution_mode}[/red]")
            raise typer.Exit(1)

        # Create TradingEngine
        engine = TradingEngine(
            strategy=strat,
            executor=executor,
            session_factory=session_factory,
            risk_settings=config.risk,
        )

        # Initialize notifier (for future use with trade notifications)
        # TODO: Integrate notifier with engine events in future phase
        if config.notifications.discord_enabled:
            _notifier = DiscordNotifier(
                webhook_url=config.notifications.discord_webhook_url.get_secret_value(),
            )
            del _notifier  # Placeholder - will be used in future phase

        # Start engine
        await engine.start()
        console.print("[green]Trading engine started[/green]")

        try:
            # TODO: Implement automated trading loop in future phase
            # TODO: Implement interactive mode in future phase
            if interactive:
                console.print("[yellow]Interactive mode not yet implemented[/yellow]")
                console.print("[yellow]Will be added in future phase[/yellow]")
            else:
                console.print("[yellow]Automated trading mode not yet implemented[/yellow]")
                console.print("[yellow]Will be added in future phase[/yellow]")

            # Keep engine running briefly for demonstration
            console.print("\n[dim]Engine will run for 5 seconds as demonstration...[/dim]")
            await asyncio.sleep(5)
        finally:
            # Graceful shutdown
            await engine.stop()
            console.print("\n[green]Trading engine stopped[/green]")

            # Display final summary
            summary = await engine.get_performance_summary()
            console.print(f"\nFinal Balance: €{summary.get('balance', 0):,.2f}")
            console.print(f"Total P&L: €{summary.get('total_pnl', 0):,.2f}")

    run_async(start_trading())


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
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Save results to JSON file."),
    ] = None,
    plot: Annotated[
        bool,
        typer.Option("--plot", help="Show equity curve plot."),
    ] = True,
    params: Annotated[
        str | None,
        typer.Option("--params", help="Strategy parameters as JSON."),
    ] = None,
) -> None:
    """Run a backtest for a strategy."""
    import json
    from datetime import UTC, datetime
    from decimal import Decimal

    from cryptrink.backtest.engine import BacktestEngine
    from cryptrink.cli.formatters import format_backtest_results_table
    from cryptrink.cli.utils import (
        create_data_feed,
        create_session_factory,
        load_strategy,
        run_async,
    )

    setup_logging()
    config = load_config(config_path)

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

    # Parse parameters
    strategy_params = {}
    if params:
        try:
            strategy_params = json.loads(params)
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON in --params: {e}[/red]")
            raise typer.Exit(1) from e

    # Parse dates
    try:
        start_time = datetime.fromisoformat(start_date).replace(tzinfo=UTC)
        end_time = (
            datetime.fromisoformat(end_date).replace(tzinfo=UTC) if end_date else datetime.now(UTC)
        )
    except ValueError as e:
        console.print(f"[red]Invalid date format: {e}[/red]")
        console.print("Expected format: YYYY-MM-DD")
        raise typer.Exit(1) from e

    async def run_backtest() -> None:
        # Load strategy
        try:
            strat = load_strategy(strategy, **strategy_params)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e

        # Create session factory and data feed
        session_factory = create_session_factory(config)
        data_feed = create_data_feed(config, session_factory)

        # Create backtest engine
        engine = BacktestEngine(
            strategy=strat,
            data_feed=data_feed,
            initial_balance=Decimal(str(initial_capital)),
            session_factory=session_factory,
            risk_settings=config.risk,
        )

        # Run backtest
        console.print("[yellow]Running backtest...[/yellow]")
        result = await engine.run(
            symbol=symbol,
            start_time=start_time,
            end_time=end_time,
            timeframe=strat.timeframe,
        )

        # Display results
        console.print("\n")
        result.print_summary()
        console.print("\n")
        console.print(format_backtest_results_table(result))

        # Plot equity curve
        if plot:
            try:
                result.plot_equity_curve()
            except Exception as e:
                console.print(f"[yellow]Could not display plot: {e}[/yellow]")

        # Save to JSON (using sync IO since we're inside async context)
        if output:
            from pathlib import Path

            Path(output).write_text(  # noqa: ASYNC240 - sync write is acceptable for one-shot CLI export
                json.dumps(result.to_dict(), indent=2)
            )
            console.print(f"\n[green]Results saved to {output}[/green]")

    run_async(run_backtest())


@app.command()
def suggest(
    strategy: Annotated[str, typer.Argument(help="Strategy to use for suggestions.")],
    symbol: Annotated[str, typer.Argument(help="Trading symbol (e.g., BTC-EUR).")],
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format (table, json)."),
    ] = "table",
    timeframe: Annotated[
        str,
        typer.Option("--timeframe", "-t", help="Timeframe (1h, 4h, 1d)."),
    ] = "1h",
    config_path: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    params: Annotated[
        str | None,
        typer.Option("--params", help="Strategy parameters as JSON."),
    ] = None,
) -> None:
    """Get trade suggestions without executing."""
    import json
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    import pandas as pd

    from cryptrink.cli.formatters import format_trade_suggestions_table
    from cryptrink.cli.utils import (
        create_data_feed,
        create_session_factory,
        load_strategy,
        run_async,
    )
    from cryptrink.strategies.base import SignalType, StrategyContext

    setup_logging()
    config = load_config(config_path)

    console.print(
        Panel(
            f"[bold magenta]Trade Suggestions[/bold magenta]\n\n"
            f"Strategy: {strategy}\n"
            f"Symbol: {symbol}\n"
            f"Timeframe: {timeframe}\n"
            f"Format: {output_format}",
            title="Suggestion Mode",
            border_style="magenta",
        )
    )

    # Parse parameters
    strategy_params = {}
    if params:
        try:
            strategy_params = json.loads(params)
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON in --params: {e}[/red]")
            raise typer.Exit(1) from e

    async def generate_suggestions() -> None:
        # Load strategy
        try:
            strat = load_strategy(strategy, **strategy_params)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e

        # Create data feed
        session_factory = create_session_factory(config)
        data_feed = create_data_feed(config, session_factory)

        # Fetch recent OHLCV data
        console.print("[yellow]Fetching market data...[/yellow]")
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(days=30)  # 30 days of history

        ohlcv_data = await data_feed.get_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
        )

        if not ohlcv_data:
            console.print(f"[red]No historical data found for {symbol}[/red]")
            raise typer.Exit(1) from None

        # Convert to DataFrame
        df = pd.DataFrame(
            {
                "open": [float(c["open"]) for c in ohlcv_data],
                "high": [float(c["high"]) for c in ohlcv_data],
                "low": [float(c["low"]) for c in ohlcv_data],
                "close": [float(c["close"]) for c in ohlcv_data],
                "volume": [float(c["volume"]) for c in ohlcv_data],
            },
            index=[c["timestamp"] for c in ohlcv_data],
        )

        # Build strategy context (HistoricalDataFeed returns dict-shaped candles)
        last_candle = ohlcv_data[-1]
        current_price = Decimal(str(last_candle["close"]))
        last_timestamp = last_candle["timestamp"]
        if not isinstance(last_timestamp, datetime):
            last_timestamp = datetime.now(UTC)
        context = StrategyContext(
            symbol=symbol,
            current_price=current_price,
            timestamp=last_timestamp,
            ohlcv=df,
            position_size=Decimal("0"),
        )

        # Generate signal
        signal = strat.generate_signal(context)

        # Display results
        if signal.signal_type == SignalType.HOLD:
            console.print("\n[yellow]No trade signal at this time (HOLD)[/yellow]")
        else:
            if output_format == "table":
                console.print("\n")
                console.print(format_trade_suggestions_table([signal]))

                # Show metadata
                if signal.metadata:
                    console.print("\n[bold]Signal Metadata:[/bold]")
                    for key, value in signal.metadata.items():
                        console.print(f"  {key}: {value}")
            else:  # json
                signal_dict = {
                    "symbol": signal.symbol,
                    "type": signal.signal_type.value,
                    "price": float(signal.price),
                    "strength": signal.strength.value,
                    "stop_loss": float(signal.stop_loss) if signal.stop_loss else None,
                    "take_profit": float(signal.take_profit) if signal.take_profit else None,
                    "timestamp": signal.timestamp.isoformat(),
                    "metadata": signal.metadata,
                }
                console.print_json(data=signal_dict)

    run_async(generate_suggestions())


@app.command()
def status(
    config_path: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    engine_id: Annotated[
        str | None,
        typer.Option("--engine-id", help="Specific engine ID to query."),
    ] = None,
) -> None:
    """Show current trading status and positions."""
    from decimal import Decimal

    from sqlalchemy import select

    from cryptrink.cli.formatters import format_engine_status_panel, format_trade_history_table
    from cryptrink.cli.utils import create_session_factory, run_async
    from cryptrink.execution.models import EngineState, Position

    setup_logging()
    config = load_config(config_path)

    async def query_status() -> None:
        session_factory = create_session_factory(config)

        async with session_factory() as session:
            # Query engine state
            if engine_id:
                engine_stmt = select(EngineState).where(EngineState.engine_id == engine_id)
            else:
                # Get most recent engine
                engine_stmt = select(EngineState).order_by(EngineState.updated_at.desc()).limit(1)

            engine_result = await session.execute(engine_stmt)
            engine_state = engine_result.scalar_one_or_none()

            if not engine_state:
                console.print(
                    Panel(
                        "[bold]Trading Status[/bold]\n\nNo active trading session.",
                        title="Status",
                        border_style="green",
                    )
                )
                return

            # Query open positions (Position has no engine_id link, so we show all open).
            position_stmt = select(Position).where(Position.status == "open")
            position_result = await session.execute(position_stmt)
            open_positions = list(position_result.scalars().all())

            unrealized_pnl_total = sum(
                (p.unrealized_pnl_decimal for p in open_positions),
                Decimal("0"),
            )

            # Build status dict
            status_dict = {
                "engine_id": engine_state.engine_id,
                "strategy": engine_state.strategy_name,
                "mode": engine_state.executor_mode,
                "is_running": engine_state.is_running,
                "balance": float(engine_state.current_balance_decimal),
                "realized_pnl": float(engine_state.total_realized_pnl_decimal),
                "unrealized_pnl": float(unrealized_pnl_total),
                "open_positions": len(open_positions),
                "signal_count": engine_state.signal_count,
                "execution_count": engine_state.execution_count,
            }

            # Display status
            console.print(format_engine_status_panel(status_dict))

            # Show open positions if any
            if open_positions:
                console.print("\n[bold]Open Positions:[/bold]")
                console.print(format_trade_history_table(open_positions))

    run_async(query_status())


@app.command()
def history(
    config_path: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    symbol: Annotated[
        str | None,
        typer.Option("--symbol", help="Filter by symbol."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Number of records to show."),
    ] = 50,
    status_filter: Annotated[
        str,
        typer.Option("--status", help="Filter by status (closed, open, all)."),
    ] = "closed",
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format (table, json)."),
    ] = "table",
    show_orders: Annotated[
        bool,
        typer.Option("--orders", help="Show orders instead of positions."),
    ] = False,
) -> None:
    """Show trade/order history from database."""

    from decimal import Decimal

    from sqlalchemy import select

    from cryptrink.cli.formatters import format_order_history_table, format_trade_history_table
    from cryptrink.cli.utils import create_session_factory, run_async
    from cryptrink.execution.models import Order, Position

    setup_logging()
    config = load_config(config_path)

    async def query_history() -> None:
        session_factory = create_session_factory(config)

        async with session_factory() as session:
            if show_orders:
                # Query orders
                order_stmt = select(Order)
                if symbol:
                    order_stmt = order_stmt.where(Order.symbol == symbol)
                order_stmt = order_stmt.order_by(Order.created_at.desc()).limit(limit)

                order_result = await session.execute(order_stmt)
                orders = list(order_result.scalars().all())

                if not orders:
                    console.print("[yellow]No orders found[/yellow]")
                    return

                if output_format == "table":
                    console.print(format_order_history_table(orders))
                else:  # json
                    orders_dict = [
                        {
                            "symbol": o.symbol,
                            "side": o.side,
                            "type": o.order_type,
                            "status": o.status,
                            "quantity": float(o.quantity_decimal),
                            "price": float(o.price_decimal)
                            if o.price_decimal is not None
                            else None,
                            "created_at": o.created_datetime.isoformat(),
                        }
                        for o in orders
                    ]
                    console.print_json(data=orders_dict)
            else:
                # Query positions
                position_stmt = select(Position)
                if symbol:
                    position_stmt = position_stmt.where(Position.symbol == symbol)
                if status_filter != "all":
                    position_stmt = position_stmt.where(Position.status == status_filter)
                position_stmt = position_stmt.order_by(Position.closed_at.desc()).limit(limit)

                position_result = await session.execute(position_stmt)
                positions = list(position_result.scalars().all())

                if not positions:
                    console.print("[yellow]No positions found[/yellow]")
                    return

                if output_format == "table":
                    console.print(format_trade_history_table(positions))

                    # Show summary statistics
                    total_trades = len(positions)
                    winning_trades = sum(1 for p in positions if p.realized_pnl_decimal > 0)
                    total_pnl = sum(
                        (p.realized_pnl_decimal for p in positions),
                        Decimal("0"),
                    )
                    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

                    console.print("\n[bold]Summary:[/bold]")
                    console.print(f"Total Trades: {total_trades}")
                    console.print(f"Win Rate: {win_rate:.1f}%")
                    console.print(f"Total P&L: €{float(total_pnl):,.2f}")
                else:  # json
                    positions_dict = [
                        {
                            "symbol": p.symbol,
                            "side": p.side,
                            "entry_price": float(p.entry_price_decimal),
                            "exit_price": (
                                float(p.exit_price_decimal)
                                if p.exit_price_decimal is not None
                                else None
                            ),
                            "pnl": float(p.realized_pnl_decimal),
                            "fees": float(p.total_fees_decimal),
                            "opened_at": p.opened_datetime.isoformat(),
                            "closed_at": (
                                p.closed_datetime.isoformat()
                                if p.closed_datetime is not None
                                else None
                            ),
                        }
                        for p in positions
                    ]
                    console.print_json(data=positions_dict)

    run_async(query_history())


if __name__ == "__main__":
    app()
