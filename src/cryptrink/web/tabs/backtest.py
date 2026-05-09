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
import matplotlib

# ``Agg`` is the headless backend; the Space process has no display server
# so the GUI backends (Tk, Qt) would error on import. Set this before
# pyplot is imported anywhere — pyplot freezes the backend on first use.
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from cryptrink.backtest.engine import BacktestEngine
from cryptrink.backtest.optimize import OBJECTIVES
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
    list_datasets_sync,
)
from cryptrink.web.tabs.backtest_tuning import (
    ManualPanel,
    TuningPanel,
    apply_best_params,
    decode_manual_params,
    empty_trials_df,
    flatten_components,
    render_manual_panels,
    render_tuning_panels,
    run_optimization,
    visibility_updates,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from cryptrink.backtest.result import BacktestResult
    from cryptrink.strategies.base import StrategyContext


# Populated by :func:`render` so the tuning module can resolve which
# component holds which strategy's parameter without a stronger
# coupling. Module-global because Gradio's render callback is the only
# place that has access to the live ``gr.Group`` instances.
_manual_panels: dict[str, ManualPanel] = {}
_tuning_panels: dict[str, TuningPanel] = {}


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


async def autofill_dates(dataset_value: str | None) -> tuple[object, object]:
    """Set Start/End to the dataset's earliest/latest dates.

    Wired to the Dataset dropdown's ``change`` event. Picking a dataset
    snaps the date inputs to "everything we have", which is the default
    most operators want — running a strategy over the full available
    history. The operator can still narrow the window manually.
    """
    if not dataset_value:
        return gr.update(), gr.update()
    try:
        symbol, timeframe = Dataset.parse(dataset_value)
    except ValueError:
        return gr.update(), gr.update()

    datasets = await list_datasets()
    match = next(
        (ds for ds in datasets if ds.symbol == symbol and ds.timeframe == timeframe),
        None,
    )
    if match is None:
        return gr.update(), gr.update()
    start_str = match.earliest.date().isoformat()
    end_str = match.latest.date().isoformat()
    return gr.update(value=start_str), gr.update(value=end_str)


# ----------------------------------------------------------------------
# Run handler (streaming)
# ----------------------------------------------------------------------


async def run_backtest(
    strategy_name: str,
    dataset_value: str | None,
    start_date: str,
    end_date: str,
    initial_capital: float,
    *manual_param_values: object,
) -> AsyncIterator[
    tuple[str, str, matplotlib.figure.Figure | None, matplotlib.figure.Figure | None, pd.DataFrame]
]:
    """Stream a backtest run.

    Yields ``(summary_md, terminal_md, equity_fig, price_fig, trades_df)``
    tuples. Every yield is a complete render of every output, so Gradio
    can update them incrementally.

    ``manual_param_values`` is the flat tuple of every strategy's
    parameter ``gr.Number`` inputs, in the order
    :func:`flatten_components` of :data:`_manual_panels` produces. We
    only consume the slice belonging to ``strategy_name``; the rest are
    inputs of currently-hidden panels.
    """
    summary_md = ""
    # ``None`` clears any previous plot and renders a blank gr.Plot.
    equity_fig: matplotlib.figure.Figure | None = None
    price_fig: matplotlib.figure.Figure | None = None
    trades_df = _empty_trades_df()

    yield (
        summary_md,
        _emit(f"backtest: starting (strategy={strategy_name!r}, dataset={dataset_value!r})"),
        equity_fig,
        price_fig,
        trades_df,
    )

    if not strategy_name:
        yield (
            summary_md,
            _emit_failure("backtest: no strategy selected"),
            equity_fig,
            price_fig,
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
            equity_fig,
            price_fig,
            trades_df,
        )
        return

    try:
        symbol, timeframe = Dataset.parse(dataset_value)
    except ValueError as exc:
        yield (
            summary_md,
            _emit_failure("backtest: malformed dataset value", exc),
            equity_fig,
            price_fig,
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
            equity_fig,
            price_fig,
            trades_df,
        )
        return
    if end_dt <= start_dt:
        yield (
            summary_md,
            _emit_failure("backtest: end date must be after start date"),
            equity_fig,
            price_fig,
            trades_df,
        )
        return

    try:
        manual_params = decode_manual_params(strategy_name, manual_param_values, _manual_panels)
    except (KeyError, ValueError) as exc:
        yield (
            summary_md,
            _emit_failure(f"backtest: invalid parameter input for {strategy_name!r}", exc),
            equity_fig,
            price_fig,
            trades_df,
        )
        return

    try:
        wrapped_strategy = resolve_strategy(strategy_name, **manual_params)
    except KeyError as exc:
        yield (
            summary_md,
            _emit_failure(f"backtest: unknown strategy {strategy_name!r}", exc),
            equity_fig,
            price_fig,
            trades_df,
        )
        return
    except (ValueError, TypeError) as exc:
        yield (
            summary_md,
            _emit_failure(
                f"backtest: strategy {strategy_name!r} rejected parameters {manual_params}",
                exc,
            ),
            equity_fig,
            price_fig,
            trades_df,
        )
        return

    if manual_params:
        _emit("backtest: parameters — " + ", ".join(f"{k}={v}" for k, v in manual_params.items()))

    if wrapped_strategy.timeframe != timeframe:
        yield (
            summary_md,
            _emit(
                f"backtest: WARNING — strategy {wrapped_strategy.name} prefers "
                f"timeframe={wrapped_strategy.timeframe!r} but the selected "
                f"dataset is {timeframe!r}. Running anyway against {timeframe!r} "
                f"because the operator selected it explicitly."
            ),
            equity_fig,
            price_fig,
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
        equity_fig,
        price_fig,
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
        equity_fig,
        price_fig,
        trades_df,
    )

    yield (
        summary_md,
        _emit("backtest: running event-driven replay…"),
        equity_fig,
        price_fig,
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
            equity_fig,
            price_fig,
            trades_df,
        )
        return
    except Exception as exc:
        yield (
            summary_md,
            _emit_failure(f"backtest: engine raised after {_format_elapsed(run_started)}", exc),
            equity_fig,
            price_fig,
            trades_df,
        )
        return

    log = _emit(f"backtest: replay finished in {_format_elapsed(run_started)}")
    log = _emit_signal_breakdown(sniffer.counts)
    log = _emit_result_summary(result)

    summary_md = _format_summary(result)
    equity_fig = _equity_figure(result)
    price_fig = await _price_figure(repository, symbol, timeframe, start_dt, end_dt)
    trades_df = _trades_dataframe(result)

    yield (summary_md, log, equity_fig, price_fig, trades_df)


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


# Maximum points rendered per chart. matplotlib copes with more than this,
# but 200 is plenty to convey shape on a few-month backtest while keeping
# the date axis labels legible.
_PLOT_MAX_POINTS = 200


def _subsample(df: pd.DataFrame, max_points: int = _PLOT_MAX_POINTS) -> pd.DataFrame:
    """Stride-subsample ``df`` to at most ``max_points`` rows.

    Keeps the first and last row regardless of stride so the chart's
    x-axis spans the full backtest window. Used only for plotting; the
    backtest itself still runs over every candle.
    """
    if len(df) <= max_points:
        return df
    stride = max(1, len(df) // max_points)
    sampled = df.iloc[::stride].copy()
    # Append the last row if the stride dropped it — preserves end-of-window.
    if not sampled.index.equals(df.iloc[[-1]].index) and df.index[-1] not in sampled.index:
        sampled = pd.concat([sampled, df.iloc[[-1]]])
    return sampled


def _format_date_axis(ax: matplotlib.axes.Axes, dates: list[datetime]) -> None:
    """Format the x-axis with date-only labels at sensible intervals.

    The user explicitly asked for "just dates with no finer granularity";
    matplotlib's auto-locator otherwise drifts down to hours/minutes on
    short windows, which is unreadable when the chart is squeezed into a
    Gradio row. We pick a locator based on the span of the data so a
    single-week backtest gets daily ticks while a multi-month backtest
    gets weekly or monthly ticks.
    """
    if not dates:
        return
    # matplotlib's date locators/formatter are not fully typed; we accept
    # the untyped-call warnings here rather than wrap every call site.
    span_days = (dates[-1] - dates[0]).days
    locator: mdates.DateLocator
    if span_days <= 14:
        locator = mdates.DayLocator()  # type: ignore[no-untyped-call]
    elif span_days <= 90:
        locator = mdates.WeekdayLocator(byweekday=mdates.MO)  # type: ignore[no-untyped-call]
    elif span_days <= 365:
        locator = mdates.MonthLocator()  # type: ignore[no-untyped-call]
    else:
        locator = mdates.MonthLocator(bymonth=(1, 4, 7, 10))  # type: ignore[no-untyped-call]
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))  # type: ignore[no-untyped-call]
    for label in ax.get_xticklabels():
        label.set_rotation(30)
        label.set_horizontalalignment("right")


def _equity_figure(result: BacktestResult) -> matplotlib.figure.Figure:
    """Render the equity curve as a matplotlib figure for ``gr.Plot``."""
    fig, ax = plt.subplots(figsize=(8, 3.2), dpi=110)
    if not result.equity_curve:
        ax.text(0.5, 0.5, "(no equity data)", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return fig

    df = pd.DataFrame([{"timestamp": ts, "equity": float(eq)} for ts, eq in result.equity_curve])
    df = _subsample(df)
    dates = list(df["timestamp"])
    ax.plot(dates, df["equity"], color="#3b82f6", linewidth=1.4)
    ax.fill_between(
        dates, df["equity"], y2=float(result.initial_balance), alpha=0.08, color="#3b82f6"
    )
    ax.axhline(float(result.initial_balance), color="#94a3b8", linewidth=0.8, linestyle="--")
    ax.set_ylabel("Equity (€)")
    ax.set_title("Equity curve")
    ax.grid(True, alpha=0.25)
    _format_date_axis(ax, dates)
    fig.tight_layout()
    return fig


async def _price_figure(
    repository: OHLCVRepository,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
) -> matplotlib.figure.Figure:
    """Render the close-price curve as a matplotlib figure for ``gr.Plot``.

    Same role as the candle plot before: confirms the data the strategy
    saw matches what the operator expects. We fetch from the repository
    rather than threading candles through the engine — pure viz.
    """
    fig, ax = plt.subplots(figsize=(8, 3.2), dpi=110)
    records = await repository.get(
        symbol,
        timeframe,
        start_time=int(start_dt.timestamp() * 1000),
        end_time=int(end_dt.timestamp() * 1000),
        limit=10_000_000,
    )
    if not records:
        ax.text(0.5, 0.5, "(no candle data)", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return fig

    df = pd.DataFrame(
        [
            {
                "timestamp": datetime.fromtimestamp(r.timestamp / 1000, tz=UTC),
                "close": float(r.close_decimal),
            }
            for r in records
        ]
    )
    df = _subsample(df)
    dates = list(df["timestamp"])
    ax.plot(dates, df["close"], color="#10b981", linewidth=1.2)
    ax.set_ylabel(f"{symbol} close")
    ax.set_title(f"{symbol} @ {timeframe} — close price (data the strategy saw)")
    ax.grid(True, alpha=0.25)
    _format_date_axis(ax, dates)
    fig.tight_layout()
    return fig


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
    # ``ensure_builtins_registered`` runs from the runtime, but resolve_strategy
    # is the lazier path; the Backtest tab is mounted after the runtime is
    # already up so this list is non-empty in practice.
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
            "Tune parameters by hand in the **Strategy parameters** accordion, or "
            "let **Auto-tuning** sweep them with grid search or Optuna's TPE sampler "
            "and pick the combination that maximises the objective you choose.\n\n"
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
            # Read the OHLCV summary synchronously so the dropdown lands
            # populated. Gradio's SSR mode rejects submitted values when
            # the server-side ``choices`` list is empty — even after a
            # later async refresh the validator still sees the original
            # render-time choices and bounces the value before any
            # handler can run. ``allow_custom_value=True`` is also kept
            # as a belt-and-braces fallback; the run handler always
            # validates via ``Dataset.parse``.
            initial_datasets = list_datasets_sync()
            initial_choices = [(ds.label, ds.value) for ds in initial_datasets]
            initial_value = initial_choices[0][1] if initial_choices else None
            dataset_input = gr.Dropdown(
                choices=initial_choices,
                value=initial_value,
                label="Dataset (symbol @ timeframe)",
                allow_custom_value=True,
            )
            refresh_datasets_btn = gr.Button("Refresh datasets", variant="secondary")

        with gr.Row():
            start_input = gr.Textbox(value="2024-01-01", label="Start (YYYY-MM-DD)")
            end_input = gr.Textbox(value="", label="End (YYYY-MM-DD, blank = now)")
            capital_input = gr.Number(value=10000.0, label="Initial capital (EUR)")

        with gr.Accordion("Strategy parameters", open=True):
            global _manual_panels
            _manual_panels = render_manual_panels(strategy_options, default_strategy)
        manual_components = flatten_components(_manual_panels)

        with gr.Accordion("Auto-tuning", open=False):
            gr.Markdown(
                "Sweep one or more parameters and pick the combination that "
                "maximises the chosen objective. Tuned parameters override "
                "the manual values above for each trial; untuned parameters "
                "keep their manual value."
            )
            with gr.Row():
                opt_mode_input = gr.Radio(
                    choices=[("Grid search", "grid"), ("Optuna TPE", "tpe")],
                    value="grid",
                    label="Search mode",
                )
                opt_objective_input = gr.Dropdown(
                    choices=[(label, key) for key, (_dir, label) in OBJECTIVES.items()],
                    value="total_return_pct",
                    label="Objective",
                )
                opt_n_trials_input = gr.Slider(
                    minimum=5,
                    maximum=200,
                    value=30,
                    step=1,
                    label="TPE trials (ignored for grid)",
                )

            global _tuning_panels
            _tuning_panels = render_tuning_panels(strategy_options, default_strategy)
            tuning_components = flatten_components(_tuning_panels)

            with gr.Row():
                run_opt_btn = gr.Button("Run optimization", variant="primary")
                apply_best_btn = gr.Button("Apply best to manual", variant="secondary")
            opt_summary_md = gr.Markdown(
                value="_Run an optimisation to see the best parameters here._"
            )
            opt_trials_df = gr.Dataframe(
                value=empty_trials_df(),
                label="Top trials (sorted by objective)",
            )
            # Holds the most recent OptimizationResult so "Apply best"
            # can push best_params back into the manual inputs without
            # re-running the sweep.
            opt_result_state = gr.State(value=None)

        with gr.Row():
            run_btn = gr.Button("Run backtest", variant="primary")
            clear_log_btn = gr.Button("Clear log")

        gr.Markdown("### Result")
        summary_output = gr.Markdown(value=_NO_DATASET_NOTICE)

        # ``gr.Plot`` renders a matplotlib Figure as an image: date-only
        # x-axis labels, no broken JS tooltips, no upside-down y-axis. The
        # cost is no live cursor, but the figure is small enough to read at
        # a glance and the trades / summary tables carry the precise numbers.
        with gr.Row():
            equity_output = gr.Plot(label="Equity curve")
            candle_output = gr.Plot(label="Close price (data the strategy saw)")
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
        # Snap Start / End to the dataset's full range whenever the
        # operator picks a new dataset — that's the default they want
        # 99% of the time. Manual narrowing still wins because they can
        # edit the textboxes after.
        dataset_input.change(
            fn=autofill_dates,
            inputs=[dataset_input],
            outputs=[start_input, end_input],
        )

        # Strategy change → toggle which manual + tuning panel is visible.
        # Both panel sets share the same strategy axis; we update them
        # in a single callback by concatenating the updates.
        manual_groups = [panel.group for panel in _manual_panels.values()]
        tuning_groups = [panel.group for panel in _tuning_panels.values()]

        def _on_strategy_change(strategy_name: str) -> list[object]:
            manual_updates = visibility_updates(strategy_name, _manual_panels)
            tuning_updates = visibility_updates(strategy_name, _tuning_panels)
            return [*manual_updates, *tuning_updates]

        strategy_input.change(
            fn=_on_strategy_change,
            inputs=[strategy_input],
            outputs=[*manual_groups, *tuning_groups],
        )

        run_btn.click(
            fn=run_backtest,
            inputs=[
                strategy_input,
                dataset_input,
                start_input,
                end_input,
                capital_input,
                *manual_components,
            ],
            outputs=[summary_output, terminal, equity_output, candle_output, trades_output],
        )
        clear_log_btn.click(fn=clear_log, inputs=[], outputs=[terminal])

        run_opt_btn.click(
            fn=run_optimization,
            inputs=[
                strategy_input,
                dataset_input,
                start_input,
                end_input,
                capital_input,
                opt_mode_input,
                opt_objective_input,
                opt_n_trials_input,
                *manual_components,
                *tuning_components,
            ],
            outputs=[opt_summary_md, terminal, opt_trials_df, opt_result_state],
        )
        apply_best_btn.click(
            fn=apply_best_params,
            inputs=[strategy_input, opt_result_state],
            outputs=manual_components,
        )
