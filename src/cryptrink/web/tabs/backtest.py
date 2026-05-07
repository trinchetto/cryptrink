"""Backtest tab for the Cryptrink Gradio web app.

Drives :class:`BacktestEngine` over a stored OHLCV ``(symbol, timeframe)``
group and surfaces three views:

* a streaming terminal log that mirrors the Data tab — every step of the
  run (data load, signal counts by type, executor outcome, final
  metrics) is written there so the operator can see *why* a strategy
  did or did not trade;
* a close-price line chart drawn from the candles the strategy actually
  saw, which is the smallest thing that confirms "the data the engine
  used is the data I expect";
* the equity curve and the trades table.

Symbol + timeframe are picked together via a Dataset dropdown sourced
from :func:`cryptrink.web.state.list_datasets` — the dropdown only lists
``(symbol, timeframe)`` groups that actually exist in the database, so
the Backtest tab cannot silently run against the wrong timeframe.
"""

from __future__ import annotations

import time
from collections import defaultdict
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
from cryptrink.strategies.base import BaseStrategy, Signal
from cryptrink.web.state import (
    Dataset,
    get_runtime,
    list_datasets,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from cryptrink.backtest.result import BacktestResult
    from cryptrink.strategies.base import StrategyContext


# ----------------------------------------------------------------------
# Terminal log (same pattern as :mod:`cryptrink.web.tabs.data`)
# ----------------------------------------------------------------------

_LOG: list[str] = []
_LOG_MAX_LINES = 200


def _now() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S")


def _emit(message: str) -> str:
    _LOG.append(f"[{_now()}] {message}")
    if len(_LOG) > _LOG_MAX_LINES:
        del _LOG[: len(_LOG) - _LOG_MAX_LINES]
    return _render_terminal()


def _render_terminal() -> str:
    if not _LOG:
        return "```\n(empty terminal — click Run backtest to log activity)\n```"
    return "```\n" + "\n".join(_LOG) + "\n```"


def _emit_failure(message: str, exc: Exception | None = None) -> str:
    if exc is not None:
        return _emit(f"FAILED: {message} ({type(exc).__name__}: {exc})")
    return _emit(f"FAILED: {message}")


def _format_elapsed(start_perf: float) -> str:
    elapsed = time.perf_counter() - start_perf
    if elapsed < 1:
        return f"{elapsed * 1000:.0f}ms"
    return f"{elapsed:.2f}s"


def clear_log() -> str:
    _LOG.clear()
    return _render_terminal()


# ----------------------------------------------------------------------
# Strategy sniffer
# ----------------------------------------------------------------------


class _SignalSniffer(BaseStrategy):
    """Wraps a strategy and counts the signal types it emits.

    Indispensable for diagnosing "the equity curve is flat" — without
    this the operator cannot tell whether the strategy emitted nothing
    (insufficient data, threshold filter), emitted only HOLDs, or
    emitted real entries that the risk validator silently rejected. We
    log the histogram once the run finishes.
    """

    def __init__(self, wrapped: BaseStrategy) -> None:
        self._wrapped = wrapped
        self.counts: dict[str, int] = defaultdict(int)
        self.last_signal: Signal | None = None

    @property
    def name(self) -> str:
        return self._wrapped.name

    @property
    def description(self) -> str:
        return self._wrapped.description

    @property
    def required_history(self) -> int:
        return self._wrapped.required_history

    @property
    def timeframe(self) -> str:
        return self._wrapped.timeframe

    def generate_signal(self, context: StrategyContext) -> Signal:
        signal = self._wrapped.generate_signal(context)
        self.counts[signal.signal_type.value] += 1
        self.last_signal = signal
        return signal


# ----------------------------------------------------------------------
# Dataset dropdown plumbing
# ----------------------------------------------------------------------


_NO_DATASET_NOTICE = (
    "_No (symbol, timeframe) groups in the database — open the Data tab and run Backfill first._"
)


async def _dataset_choices() -> list[tuple[str, str]]:
    """Return Gradio-friendly ``(label, value)`` pairs for the dropdown."""
    datasets = await list_datasets()
    return [(ds.label, ds.value) for ds in datasets]


async def refresh_datasets(current: str | None) -> tuple[object, str]:
    """Re-query the OHLCV table and update the Dataset dropdown.

    The Backtest, Suggest, and Live tabs each own their own dropdown
    instance because Gradio dropdowns can't be shared across tabs, but
    they all read from :func:`list_datasets` so a Backfill on the Data
    tab + a Refresh here propagates the new vocabulary.
    """
    started = time.perf_counter()
    _emit("datasets: refreshing from OHLCV table…")
    try:
        choices = await _dataset_choices()
    except Exception as exc:
        return gr.update(), _emit_failure("datasets: refresh failed", exc)

    if not choices:
        log = _emit(
            "datasets: refreshed — 0 (symbol, timeframe) groups stored. "
            "Open the Data tab and run Backfill to populate the dropdown."
        )
        return gr.update(choices=[], value=None), log

    values = {value for _, value in choices}
    new_value = current if current in values else choices[0][1]
    log = _emit(
        f"datasets: refreshed — {len(choices)} group(s) available ({_format_elapsed(started)})"
    )
    return gr.update(choices=choices, value=new_value), log


# ----------------------------------------------------------------------
# Run handler (streaming)
# ----------------------------------------------------------------------


async def run_backtest(
    strategy_name: str,
    dataset_value: str | None,
    start_date: str,
    end_date: str,
    initial_capital: float,
) -> AsyncIterator[tuple[str, str, pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    """Stream a backtest run.

    Yields ``(summary_md, terminal_md, equity_df, candle_df, trades_df)``
    tuples. Every yield is a complete render of every output, so Gradio
    can update them incrementally.
    """
    summary_md = ""
    equity_df = pd.DataFrame(columns=["timestamp", "equity"])
    candle_df = pd.DataFrame(columns=["timestamp", "close"])
    trades_df = _empty_trades_df()

    yield (
        summary_md,
        _emit(f"backtest: starting (strategy={strategy_name!r}, dataset={dataset_value!r})"),
        equity_df,
        candle_df,
        trades_df,
    )

    if not strategy_name:
        yield (
            summary_md,
            _emit_failure("backtest: no strategy selected"),
            equity_df,
            candle_df,
            trades_df,
        )
        return
    if not dataset_value:
        yield (
            summary_md,
            _emit_failure(
                "backtest: no dataset selected. Open the Data tab, run Backfill, "
                "then click Refresh datasets here."
            ),
            equity_df,
            candle_df,
            trades_df,
        )
        return

    try:
        symbol, timeframe = Dataset.parse(dataset_value)
    except ValueError as exc:
        yield (
            summary_md,
            _emit_failure("backtest: malformed dataset value", exc),
            equity_df,
            candle_df,
            trades_df,
        )
        return

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
        end_dt = (
            datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
            if end_date
            else datetime.now(UTC)
        )
    except ValueError as exc:
        yield (
            summary_md,
            _emit_failure("backtest: invalid date", exc),
            equity_df,
            candle_df,
            trades_df,
        )
        return
    if end_dt <= start_dt:
        yield (
            summary_md,
            _emit_failure("backtest: end date must be after start date"),
            equity_df,
            candle_df,
            trades_df,
        )
        return

    try:
        wrapped_strategy = resolve_strategy(strategy_name)
    except KeyError as exc:
        yield (
            summary_md,
            _emit_failure(f"backtest: unknown strategy {strategy_name!r}", exc),
            equity_df,
            candle_df,
            trades_df,
        )
        return

    if wrapped_strategy.timeframe != timeframe:
        yield (
            summary_md,
            _emit(
                f"backtest: WARNING — strategy {wrapped_strategy.name} prefers "
                f"timeframe={wrapped_strategy.timeframe!r} but the selected "
                f"dataset is {timeframe!r}. Running anyway against {timeframe!r} "
                f"because the operator selected it explicitly."
            ),
            equity_df,
            candle_df,
            trades_df,
        )

    runtime = get_runtime()
    session_factory = runtime.session_factory
    db_engine = session_factory.kw["bind"]
    async with db_engine.begin() as conn:
        await conn.run_sync(OHLCVModel.metadata.create_all)
        await conn.run_sync(Position.metadata.create_all)
    yield (
        summary_md,
        _emit(
            f"backtest: dataset={symbol} @ {timeframe}; "
            f"window={start_dt.date()} → {end_dt.date()}; "
            f"capital=€{initial_capital:,.2f}"
        ),
        equity_df,
        candle_df,
        trades_df,
    )

    repository = OHLCVRepository(session_factory)
    data_feed = HistoricalDataFeed(repository)
    sniffer = _SignalSniffer(wrapped_strategy)

    engine = BacktestEngine(
        strategy=sniffer,
        data_feed=data_feed,
        initial_balance=Decimal(str(initial_capital)),
        session_factory=session_factory,
        risk_settings=runtime.settings.risk,
    )
    yield (
        summary_md,
        _emit(
            f"backtest: engine built (strategy.required_history="
            f"{wrapped_strategy.required_history}, lookback_periods=200)"
        ),
        equity_df,
        candle_df,
        trades_df,
    )

    yield (
        summary_md,
        _emit("backtest: running event-driven replay…"),
        equity_df,
        candle_df,
        trades_df,
    )

    run_started = time.perf_counter()
    try:
        result = await engine.run(
            symbol=symbol,
            start_time=start_dt,
            end_time=end_dt,
            timeframe=timeframe,
        )
    except ValueError as exc:
        yield (
            summary_md,
            _emit_failure(
                f"backtest: no historical data for {symbol} {timeframe} in window "
                f"({_format_elapsed(run_started)}). Use the Data tab to backfill first.",
                exc,
            ),
            equity_df,
            candle_df,
            trades_df,
        )
        return
    except Exception as exc:
        yield (
            summary_md,
            _emit_failure(f"backtest: engine raised after {_format_elapsed(run_started)}", exc),
            equity_df,
            candle_df,
            trades_df,
        )
        return

    log = _emit(f"backtest: replay finished in {_format_elapsed(run_started)}")
    log = _emit_signal_breakdown(sniffer.counts)
    log = _emit_result_summary(result)

    summary_md = _format_summary(result)
    equity_df = _equity_dataframe(result)
    candle_df = await _candle_dataframe(repository, symbol, timeframe, start_dt, end_dt)
    trades_df = _trades_dataframe(result)

    yield (summary_md, log, equity_df, candle_df, trades_df)


def _emit_signal_breakdown(counts: dict[str, int]) -> str:
    """Log a one-line histogram of the signals the strategy emitted."""
    if not counts:
        return _emit("backtest: signals — strategy was never called (no in-window candles?)")
    parts = ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))
    total = sum(counts.values())
    return _emit(f"backtest: signals — {total} total ({parts})")


def _emit_result_summary(result: BacktestResult) -> str:
    metrics = result.metrics
    return _emit(
        f"backtest: COMPLETE — trades={metrics.total_trades}, "
        f"return={metrics.total_return_pct * 100:+.2f}%, "
        f"sharpe={metrics.sharpe_ratio:.2f}, "
        f"final_equity=€{metrics.ending_equity:,.2f}"
    )


# ----------------------------------------------------------------------
# Output formatting
# ----------------------------------------------------------------------


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


async def _candle_dataframe(
    repository: OHLCVRepository,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
) -> pd.DataFrame:
    """Pull the OHLCV rows the backtest actually ran against, for plotting.

    We re-read from the repository (cheap on SQLite) rather than thread
    them through the engine result; the engine's responsibility is the
    backtest, not the viz.
    """
    records = await repository.get(
        symbol,
        timeframe,
        start_time=int(start_dt.timestamp() * 1000),
        end_time=int(end_dt.timestamp() * 1000),
        limit=100_000,
    )
    if not records:
        return pd.DataFrame(columns=["timestamp", "close"])
    return pd.DataFrame(
        [
            {
                "timestamp": datetime.fromtimestamp(r.timestamp / 1000, tz=UTC),
                "close": float(r.close_decimal),
            }
            for r in records
        ]
    )


def _empty_trades_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "opened_at",
            "closed_at",
            "side",
            "quantity",
            "entry_price",
            "exit_price",
            "realized_pnl",
        ]
    )


def _trades_dataframe(result: BacktestResult) -> pd.DataFrame:
    if not result.trades:
        return _empty_trades_df()
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
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------


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
        gr.Markdown(
            "Replay a strategy over a stored OHLCV ``(symbol, timeframe)`` group. "
            "The Dataset dropdown lists what is actually persisted in the database "
            "— if it's empty, open the Data tab and run Backfill first.\n\n"
            "The terminal at the bottom logs every step of the run, including the "
            "histogram of signals the strategy emitted, so you can tell whether "
            "the strategy is firing entries at all."
        )

        with gr.Row():
            strategy_input = gr.Dropdown(
                choices=strategy_options,
                value=default_strategy,
                label="Strategy",
            )
            # Dataset dropdown starts empty; the Refresh button below populates
            # it. We can't `await list_datasets()` here because render() is sync.
            dataset_input = gr.Dropdown(
                choices=[],
                value=None,
                label="Dataset (symbol @ timeframe)",
                allow_custom_value=False,
            )
            refresh_datasets_btn = gr.Button("Refresh datasets", variant="secondary")

        with gr.Row():
            start_input = gr.Textbox(value="2024-01-01", label="Start (YYYY-MM-DD)")
            end_input = gr.Textbox(value="", label="End (YYYY-MM-DD, blank = now)")
            capital_input = gr.Number(value=10000.0, label="Initial capital (EUR)")

        with gr.Row():
            run_btn = gr.Button("Run backtest", variant="primary")
            clear_log_btn = gr.Button("Clear log")

        gr.Markdown("### Result")
        summary_output = gr.Markdown(value=_NO_DATASET_NOTICE)

        with gr.Row():
            equity_output = gr.LinePlot(
                x="timestamp",
                y="equity",
                title="Equity curve",
                height=280,
            )
            candle_output = gr.LinePlot(
                x="timestamp",
                y="close",
                title="Close price (data the strategy saw)",
                height=280,
            )
        trades_output = gr.Dataframe(label="Closed trades")

        gr.Markdown("### Terminal")
        terminal = gr.Markdown(value=_render_terminal())

        # Auto-populate the dataset dropdown on tab load. ``demo.load`` would
        # be cleaner but it lives on the parent Blocks; instead we trigger
        # the same refresh whenever the strategy changes (which the operator
        # always does first) and via the explicit Refresh button.
        refresh_datasets_btn.click(
            fn=refresh_datasets,
            inputs=[dataset_input],
            outputs=[dataset_input, terminal],
        )
        # Lazy-populate on first focus too: when the dropdown is first
        # focused, refresh if it is empty. Gradio doesn't expose a direct
        # "on first interaction" event, but `select` fires on open; using
        # it with `current=None` does the right thing.
        dataset_input.focus(
            fn=refresh_datasets,
            inputs=[dataset_input],
            outputs=[dataset_input, terminal],
        )

        run_btn.click(
            fn=run_backtest,
            inputs=[strategy_input, dataset_input, start_input, end_input, capital_input],
            outputs=[summary_output, terminal, equity_output, candle_output, trades_output],
        )
        clear_log_btn.click(fn=clear_log, inputs=[], outputs=[terminal])
