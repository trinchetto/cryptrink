"""Backtest tab for the Cryptrink Gradio web app."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import gradio as gr
import pandas as pd

from cryptrink.backtest.engine import BacktestEngine
from cryptrink.data.feed import HistoricalDataFeed
from cryptrink.data.storage import OHLCV as OHLCVModel
from cryptrink.data.storage import OHLCVRepository
from cryptrink.execution.models import Position
from cryptrink.runtime import resolve_strategy
from cryptrink.strategies import registry as strategy_registry
from cryptrink.web.state import default_symbol, get_runtime, get_symbol_choices

if TYPE_CHECKING:
    from cryptrink.backtest.result import BacktestResult


async def run_backtest(
    strategy_name: str,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """Run a backtest and return summary, equity curve, and trades.

    Raises:
        gr.Error: For invalid inputs or backtest failures.
    """
    if not strategy_name:
        raise gr.Error("Select a strategy.")
    if not symbol:
        raise gr.Error("Enter a symbol.")

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
        end_dt = (
            datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
            if end_date
            else datetime.now(UTC)
        )
    except ValueError as exc:
        raise gr.Error(f"Invalid date: {exc}") from exc

    if end_dt <= start_dt:
        raise gr.Error("End date must be after start date.")

    runtime = get_runtime()

    try:
        strategy = resolve_strategy(strategy_name)
    except KeyError as exc:
        raise gr.Error(f"Unknown strategy '{strategy_name}'.") from exc

    session_factory = runtime.session_factory
    db_engine = session_factory.kw["bind"]
    async with db_engine.begin() as conn:
        await conn.run_sync(OHLCVModel.metadata.create_all)
        await conn.run_sync(Position.metadata.create_all)

    repository = OHLCVRepository(session_factory)
    data_feed = HistoricalDataFeed(repository)

    engine = BacktestEngine(
        strategy=strategy,
        data_feed=data_feed,
        initial_balance=Decimal(str(initial_capital)),
        session_factory=session_factory,
        risk_settings=runtime.settings.risk,
    )

    try:
        result = await engine.run(
            symbol=symbol,
            start_time=start_dt,
            end_time=end_dt,
        )
    except ValueError as exc:
        raise gr.Error(
            f"Backtest failed: {exc}. Load historical OHLCV data into the database first."
        ) from exc

    return (
        _format_summary(result),
        _equity_dataframe(result),
        _trades_dataframe(result),
    )


def _format_summary(result: BacktestResult) -> str:
    metrics = result.metrics
    return (
        f"### {result.strategy_name} on {result.symbol} ({result.timeframe})\n\n"
        f"**Period:** {result.start_time.date()} to {result.end_time.date()}\n\n"
        "| Metric | Value |\n"
        "| --- | --- |\n"
        f"| Initial balance | €{result.initial_balance:,.2f} |\n"
        f"| Final equity | €{metrics.ending_equity:,.2f} |\n"
        f"| Total return | €{metrics.total_return:,.2f} "
        f"({metrics.total_return_pct * 100:.2f}%) |\n"
        f"| Annualised return | {metrics.annualized_return * 100:.2f}% |\n"
        f"| Sharpe ratio | {metrics.sharpe_ratio:.2f} |\n"
        f"| Sortino ratio | {metrics.sortino_ratio:.2f} |\n"
        f"| Max drawdown | {metrics.max_drawdown * 100:.2f}% |\n"
        f"| Total trades | {metrics.total_trades} |\n"
        f"| Win rate | {metrics.win_rate * 100:.1f}% |\n"
        f"| Profit factor | {metrics.profit_factor:.2f} |\n"
    )


def _equity_dataframe(result: BacktestResult) -> pd.DataFrame:
    if not result.equity_curve:
        return pd.DataFrame(columns=["timestamp", "equity"])
    return pd.DataFrame([{"timestamp": ts, "equity": float(eq)} for ts, eq in result.equity_curve])


def _trades_dataframe(result: BacktestResult) -> pd.DataFrame:
    columns = [
        "opened_at",
        "closed_at",
        "side",
        "quantity",
        "entry_price",
        "exit_price",
        "realized_pnl",
    ]
    if not result.trades:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "opened_at": pos.opened_datetime,
            "closed_at": pos.closed_datetime,
            "side": pos.side,
            "quantity": float(pos.quantity_decimal),
            "entry_price": float(pos.entry_price_decimal),
            "exit_price": (
                float(pos.exit_price_decimal) if pos.exit_price_decimal is not None else None
            ),
            "realized_pnl": float(pos.realized_pnl_decimal),
        }
        for pos in result.trades
    ]
    return pd.DataFrame(rows, columns=columns)


def render() -> None:
    """Render the Backtest tab UI inside an enclosing :class:`gr.Tabs`."""
    runtime = get_runtime()
    strategy_options = strategy_registry.list_strategies()
    default_strategy = (
        runtime.settings.default_strategy
        if runtime.settings.default_strategy in strategy_options
        else (strategy_options[0] if strategy_options else None)
    )
    with gr.Tab("Backtest"):
        gr.Markdown("Replay a strategy against historical OHLCV stored in the configured database.")
        with gr.Row():
            strategy_input = gr.Dropdown(
                choices=strategy_options,
                value=default_strategy,
                label="Strategy",
            )
            symbol_input = gr.Dropdown(
                choices=get_symbol_choices(),
                value=default_symbol(),
                label="Symbol",
                allow_custom_value=True,
            )
        with gr.Row():
            start_input = gr.Textbox(value="2024-01-01", label="Start (YYYY-MM-DD)")
            end_input = gr.Textbox(value="", label="End (YYYY-MM-DD, blank = now)")
            capital_input = gr.Number(value=10000.0, label="Initial capital (EUR)")

        run_btn = gr.Button("Run backtest", variant="primary")

        summary_output = gr.Markdown()
        equity_output = gr.LinePlot(
            x="timestamp",
            y="equity",
            title="Equity curve",
            height=280,
        )
        trades_output = gr.Dataframe(label="Closed trades")

        run_btn.click(
            fn=run_backtest,
            inputs=[strategy_input, symbol_input, start_input, end_input, capital_input],
            outputs=[summary_output, equity_output, trades_output],
        )
