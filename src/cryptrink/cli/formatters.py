"""Rich formatters for CLI output."""

from decimal import Decimal
from typing import Any

from rich.panel import Panel
from rich.table import Table

from cryptrink.backtest.result import BacktestResult
from cryptrink.execution.models import Order, Position
from cryptrink.strategies.base import Signal


def format_backtest_results_table(result: BacktestResult) -> Table:
    """Create Rich table for backtest results.

    Args:
        result: Backtest result with metrics.

    Returns:
        Rich Table with formatted metrics.
    """
    table = Table(title=f"Backtest Results: {result.strategy_name}", show_header=False)
    table.add_column("Metric", style="cyan", width=30)
    table.add_column("Value", style="bold")

    m = result.metrics

    # Returns section
    table.add_row("Total Return", f"[green]{float(m.total_return_pct) * 100:.2f}%[/green]")
    table.add_row("Annualized Return", f"{float(m.annualized_return):.2f}%")

    # Risk metrics
    table.add_row("Sharpe Ratio", f"{float(m.sharpe_ratio):.2f}")
    table.add_row("Sortino Ratio", f"{float(m.sortino_ratio):.2f}")
    table.add_row("Max Drawdown", f"[red]{float(m.max_drawdown) * 100:.2f}%[/red]")

    # Trade statistics
    table.add_row("Total Trades", str(m.total_trades))
    table.add_row("Win Rate", f"{float(m.win_rate) * 100:.1f}%")
    table.add_row("Profit Factor", f"{float(m.profit_factor):.2f}")
    table.add_row("Avg Win", f"€{float(m.avg_win):.2f}")
    table.add_row("Avg Loss", f"€{float(m.avg_loss):.2f}")

    # Equity
    table.add_row("Starting Equity", f"€{float(m.starting_equity):,.2f}")
    table.add_row("Ending Equity", f"€{float(m.ending_equity):,.2f}")

    return table


def format_trade_suggestions_table(signals: list[Signal]) -> Table:
    """Create Rich table for trade suggestions.

    Args:
        signals: List of trading signals.

    Returns:
        Rich Table with formatted signals.
    """
    table = Table(title="Trade Suggestions")
    table.add_column("Symbol", style="cyan")
    table.add_column("Type", style="bold")
    table.add_column("Price", justify="right")
    table.add_column("Strength", style="yellow")
    table.add_column("Stop Loss", justify="right")
    table.add_column("Take Profit", justify="right")

    for signal in signals:
        signal_type_str = signal.signal_type.value.upper()
        color = (
            "green"
            if "LONG" in signal_type_str
            else "red"
            if "SHORT" in signal_type_str
            else "white"
        )

        table.add_row(
            signal.symbol,
            f"[{color}]{signal_type_str}[/{color}]",
            f"€{float(signal.price):.2f}",
            signal.strength.value,
            f"€{float(signal.stop_loss):.2f}" if signal.stop_loss else "—",
            f"€{float(signal.take_profit):.2f}" if signal.take_profit else "—",
        )

    return table


def format_trade_history_table(positions: list[Position]) -> Table:
    """Create Rich table for trade history.

    Args:
        positions: List of closed positions.

    Returns:
        Rich Table with formatted trade history.
    """
    table = Table(title="Trade History")
    table.add_column("Symbol", style="cyan")
    table.add_column("Side", style="bold")
    table.add_column("Entry", justify="right")
    table.add_column("Exit", justify="right")
    table.add_column("P&L", justify="right")
    table.add_column("Fees", justify="right")
    table.add_column("Opened", style="dim")
    table.add_column("Closed", style="dim")

    for pos in positions:
        pnl = Decimal(pos.realized_pnl) if pos.realized_pnl else Decimal("0")
        pnl_color = "green" if pnl > 0 else "red"
        side_color = "green" if pos.side == "long" else "red"

        # Convert Unix timestamp to datetime string
        from datetime import UTC, datetime

        opened_str = datetime.fromtimestamp(pos.opened_at / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")
        closed_str = (
            datetime.fromtimestamp(pos.closed_at / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")
            if pos.closed_at
            else "—"
        )

        table.add_row(
            pos.symbol,
            f"[{side_color}]{pos.side.upper()}[/{side_color}]",
            f"€{float(pos.entry_price):.2f}",
            f"€{float(pos.exit_price):.2f}" if pos.exit_price else "—",
            f"[{pnl_color}]€{float(pnl):.2f}[/{pnl_color}]",
            f"€{float(pos.total_fees or 0):.2f}",
            opened_str,
            closed_str,
        )

    return table


def format_order_history_table(orders: list[Order]) -> Table:
    """Create Rich table for order history.

    Args:
        orders: List of orders.

    Returns:
        Rich Table with formatted order history.
    """
    table = Table(title="Order History")
    table.add_column("Symbol", style="cyan")
    table.add_column("Side", style="bold")
    table.add_column("Type", style="yellow")
    table.add_column("Status", style="bold")
    table.add_column("Quantity", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Created", style="dim")

    for order in orders:
        side_color = "green" if order.side == "buy" else "red"
        status_color = (
            "green"
            if order.status == "filled"
            else "yellow"
            if order.status == "pending"
            else "red"
        )

        # Convert Unix timestamp to datetime string
        from datetime import UTC, datetime

        created_str = datetime.fromtimestamp(order.created_at / 1000, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        table.add_row(
            order.symbol,
            f"[{side_color}]{order.side.upper()}[/{side_color}]",
            order.order_type.upper(),
            f"[{status_color}]{order.status.upper()}[/{status_color}]",
            f"{float(order.quantity):.8f}",
            f"€{float(order.price):.2f}" if order.price else "MARKET",
            created_str,
        )

    return table


def format_engine_status_panel(status: dict[str, Any]) -> Panel:
    """Create Rich panel for engine status.

    Args:
        status: Engine status dictionary.

    Returns:
        Rich Panel with formatted status.
    """
    content = f"""[bold]Engine ID:[/bold] {status.get('engine_id', 'N/A')}
[bold]Strategy:[/bold] {status.get('strategy', 'N/A')}
[bold]Mode:[/bold] {status.get('mode', 'N/A')}
[bold]Running:[/bold] {'✅ Yes' if status.get('is_running') else '❌ No'}

[bold cyan]Balance & P&L:[/bold cyan]
Balance: €{status.get('balance', 0):,.2f}
Realized P&L: €{status.get('realized_pnl', 0):,.2f}
Unrealized P&L: €{status.get('unrealized_pnl', 0):,.2f}

[bold cyan]Positions:[/bold cyan]
Open Positions: {status.get('open_positions', 0)}

[bold cyan]Activity:[/bold cyan]
Signals Processed: {status.get('signal_count', 0)}
Executions: {status.get('execution_count', 0)}
"""

    return Panel(content, title="Trading Engine Status", border_style="green")
