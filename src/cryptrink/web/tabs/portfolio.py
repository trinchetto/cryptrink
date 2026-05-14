"""Portfolio tab for the Cryptrink Gradio web app.

Lets the operator edit a YAML portfolio config, save it under
``data/portfolios/<name>.yaml``, and run an aggregate backtest across
every allocation in one shot. Outputs:

* a streaming terminal that mirrors the Backtest tab's pattern, so
  every step is visible (data load per pair, signal histogram per
  allocation, executor outcome, final metrics);
* an aggregate equity curve + drawdown for the whole portfolio;
* a per-allocation breakdown table that attributes realised P&L to
  each (symbol, strategy) pair.

We deliberately keep the editor as a ``gr.Code(language='yaml')``
textbox in this first cut. A row-by-row form-based editor is friendlier
but materially more code, and YAML in the repo is the source of truth
either way. A form view can layer on top in Phase 1.5.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import gradio as gr
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from cryptrink.data.feed import HistoricalDataFeed
from cryptrink.data.storage import OHLCV as OHLCVModel
from cryptrink.data.storage import OHLCVRepository
from cryptrink.execution.models import Position
from cryptrink.portfolio.engine import PortfolioBacktestEngine
from cryptrink.portfolio.models import (
    dump_yaml,
    example_portfolio,
    load_yaml,
)
from cryptrink.portfolio.storage import (
    DEFAULT_PORTFOLIO_DIR,
    delete_portfolio,
    list_portfolio_names,
    load_portfolio,
    save_portfolio,
)
from cryptrink.web.state import get_runtime

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from cryptrink.portfolio.result import PortfolioBacktestResult


# ----------------------------------------------------------------------
# Terminal log (same pattern as :mod:`cryptrink.web.tabs.backtest`)
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
        return "```\n(empty terminal — click Run portfolio backtest to log activity)\n```"
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
# YAML editor handlers
# ----------------------------------------------------------------------


def _portfolio_choices() -> list[str]:
    return list_portfolio_names()


def refresh_portfolios(current: str | None) -> tuple[object, str]:
    names = _portfolio_choices()
    log = _emit(f"portfolios: refreshed — {len(names)} on disk ({DEFAULT_PORTFOLIO_DIR})")
    if not names:
        return gr.update(choices=[], value=None), log
    new_value = current if current in names else names[0]
    return gr.update(choices=names, value=new_value), log


def load_portfolio_yaml(name: str | None) -> tuple[str, str]:
    """Load YAML from disk into the editor."""
    if not name:
        return "", _emit("portfolio: no portfolio selected")
    try:
        portfolio = load_portfolio(name)
    except (FileNotFoundError, ValueError) as exc:
        return "", _emit_failure(f"portfolio: failed to load {name!r}", exc)
    return dump_yaml(portfolio), _emit(f"portfolio: loaded {name!r} from disk")


def new_portfolio_yaml() -> tuple[str, str]:
    """Reset the editor to the example portfolio."""
    return dump_yaml(example_portfolio()), _emit("portfolio: editor seeded with example")


def save_portfolio_yaml(yaml_text: str) -> tuple[object, str]:
    """Parse the editor, validate, and write to disk under the portfolio's own name."""
    try:
        portfolio = load_yaml(yaml_text)
    except (ValueError, Exception) as exc:
        return gr.update(), _emit_failure("portfolio: YAML failed to parse", exc)
    try:
        path = save_portfolio(portfolio)
    except ValueError as exc:
        return gr.update(), _emit_failure("portfolio: validation failed", exc)
    log = _emit(f"portfolio: saved {portfolio.name!r} → {path}")
    return gr.update(choices=_portfolio_choices(), value=portfolio.name), log


def delete_portfolio_handler(name: str | None) -> tuple[object, str, str]:
    if not name:
        return gr.update(), "", _emit("portfolio: no portfolio selected to delete")
    if not delete_portfolio(name):
        return gr.update(), "", _emit_failure(f"portfolio: {name!r} not found on disk")
    names = _portfolio_choices()
    new_value = names[0] if names else None
    log = _emit(f"portfolio: deleted {name!r}")
    return gr.update(choices=names, value=new_value), "", log


# ----------------------------------------------------------------------
# Run handler (streaming)
# ----------------------------------------------------------------------


async def run_portfolio_backtest(
    yaml_text: str,
    start_date: str,
    end_date: str,
) -> AsyncIterator[tuple[str, str, matplotlib.figure.Figure | None, pd.DataFrame, pd.DataFrame]]:
    """Stream a portfolio backtest run.

    Yields ``(summary_md, terminal_md, equity_fig, breakdown_df,
    trades_df)``. Every yield is a complete render so Gradio can update
    incrementally.
    """
    summary_md = ""
    equity_fig: matplotlib.figure.Figure | None = None
    breakdown_df = _empty_breakdown_df()
    trades_df = _empty_trades_df()

    yield (summary_md, _emit("portfolio: starting"), equity_fig, breakdown_df, trades_df)

    try:
        portfolio = load_yaml(yaml_text)
    except Exception as exc:
        yield (
            summary_md,
            _emit_failure("portfolio: YAML failed to parse", exc),
            equity_fig,
            breakdown_df,
            trades_df,
        )
        return

    errors = portfolio.validate()
    if errors:
        yield (
            summary_md,
            _emit_failure("portfolio: invalid config — " + "; ".join(errors)),
            equity_fig,
            breakdown_df,
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
            _emit_failure("portfolio: invalid date", exc),
            equity_fig,
            breakdown_df,
            trades_df,
        )
        return
    if end_dt <= start_dt:
        yield (
            summary_md,
            _emit_failure("portfolio: end date must be after start date"),
            equity_fig,
            breakdown_df,
            trades_df,
        )
        return

    runtime = get_runtime()
    session_factory = runtime.session_factory
    db_engine = session_factory.kw["bind"]
    async with db_engine.begin() as conn:
        await conn.run_sync(OHLCVModel.metadata.create_all)
        await conn.run_sync(Position.metadata.create_all)

    yield (
        summary_md,
        _emit(
            f"portfolio: {portfolio.name!r} @ {portfolio.timeframe} — "
            f"{len(portfolio.enabled_allocations())} allocations, "
            f"capital=€{portfolio.initial_balance:,.2f}, "
            f"window={start_dt.date()} → {end_dt.date()}"
        ),
        equity_fig,
        breakdown_df,
        trades_df,
    )

    repository = OHLCVRepository(session_factory)
    data_feed = HistoricalDataFeed(repository)
    engine = PortfolioBacktestEngine(
        portfolio=portfolio,
        data_feed=data_feed,
        session_factory=session_factory,
        risk_settings=runtime.settings.risk,
    )

    yield (
        summary_md,
        _emit("portfolio: engine built — running event-driven replay…"),
        equity_fig,
        breakdown_df,
        trades_df,
    )

    started = time.perf_counter()
    try:
        result = await engine.run(start_time=start_dt, end_time=end_dt)
    except ValueError as exc:
        yield (
            summary_md,
            _emit_failure(f"portfolio: backtest failed after {_format_elapsed(started)}", exc),
            equity_fig,
            breakdown_df,
            trades_df,
        )
        return
    except Exception as exc:
        yield (
            summary_md,
            _emit_failure(f"portfolio: engine raised after {_format_elapsed(started)}", exc),
            equity_fig,
            breakdown_df,
            trades_df,
        )
        return

    log = _emit(f"portfolio: replay finished in {_format_elapsed(started)}")
    log = _emit_signal_breakdown(engine.signal_counts)
    log = _emit_result_summary(result)

    summary_md = _format_summary(result)
    equity_fig = _equity_figure(result)
    breakdown_df = _breakdown_dataframe(result)
    trades_df = _trades_dataframe(result)

    yield (summary_md, log, equity_fig, breakdown_df, trades_df)


def _emit_signal_breakdown(counts: dict[str, dict[str, int]]) -> str:
    if not counts:
        return _emit("portfolio: signals — no allocations were called")
    lines = []
    for symbol, hist in sorted(counts.items()):
        total = sum(hist.values())
        parts = ", ".join(f"{n} {name}" for name, n in sorted(hist.items()))
        lines.append(f"  {symbol}: {total} signals ({parts})")
    return _emit("portfolio: signals per allocation —\n" + "\n".join(lines))


def _emit_result_summary(result: PortfolioBacktestResult) -> str:
    metrics = result.metrics
    return _emit(
        f"portfolio: COMPLETE — trades={metrics.total_trades}, "
        f"return={float(metrics.total_return_pct) * 100:+.2f}%, "
        f"sharpe={float(metrics.sharpe_ratio):.2f}, "
        f"final_equity=€{metrics.ending_equity:,.2f}"
    )


# ----------------------------------------------------------------------
# Output formatting
# ----------------------------------------------------------------------


def _format_summary(result: PortfolioBacktestResult) -> str:
    metrics = result.metrics
    portfolio = result.portfolio
    return (
        f"### Portfolio `{portfolio.name}` @ {portfolio.timeframe}\n\n"
        f"**Period:** {result.start_time.date()} to {result.end_time.date()} | "
        f"**Allocations:** {len(portfolio.enabled_allocations())}\n\n"
        "| Metric | Value |\n"
        "| --- | --- |\n"
        f"| Initial balance | €{result.initial_balance:,.2f} |\n"
        f"| Final equity | €{metrics.ending_equity:,.2f} |\n"
        f"| Total return | €{metrics.total_return:,.2f} "
        f"({float(metrics.total_return_pct) * 100:+.2f}%) |\n"
        f"| Annualised return | {float(metrics.annualized_return) * 100:.2f}% |\n"
        f"| Sharpe ratio | {float(metrics.sharpe_ratio):.2f} |\n"
        f"| Sortino ratio | {float(metrics.sortino_ratio):.2f} |\n"
        f"| Max drawdown | {float(metrics.max_drawdown) * 100:.2f}% |\n"
        f"| Total trades | {metrics.total_trades} |\n"
        f"| Win rate | {float(metrics.win_rate) * 100:.1f}% |\n"
        f"| Profit factor | {float(metrics.profit_factor):.2f} |\n"
    )


_PLOT_MAX_POINTS = 200


def _subsample(df: pd.DataFrame, max_points: int = _PLOT_MAX_POINTS) -> pd.DataFrame:
    if len(df) <= max_points:
        return df
    stride = max(1, len(df) // max_points)
    sampled = df.iloc[::stride].copy()
    if not sampled.index.equals(df.iloc[[-1]].index) and df.index[-1] not in sampled.index:
        sampled = pd.concat([sampled, df.iloc[[-1]]])
    return sampled


def _format_date_axis(ax: matplotlib.axes.Axes, dates: list[datetime]) -> None:
    if not dates:
        return
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


def _equity_figure(result: PortfolioBacktestResult) -> matplotlib.figure.Figure:
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
        dates,
        df["equity"],
        y2=float(result.initial_balance),
        alpha=0.08,
        color="#3b82f6",
    )
    ax.axhline(float(result.initial_balance), color="#94a3b8", linewidth=0.8, linestyle="--")
    ax.set_ylabel("Portfolio equity (€)")
    ax.set_title(f"Portfolio `{result.portfolio.name}` — aggregate equity")
    ax.grid(True, alpha=0.25)
    _format_date_axis(ax, dates)
    fig.tight_layout()
    return fig


def _empty_breakdown_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "symbol",
            "strategy",
            "trades",
            "win_rate_pct",
            "realized_pnl",
            "best_trade",
            "worst_trade",
        ]
    )


def _breakdown_dataframe(result: PortfolioBacktestResult) -> pd.DataFrame:
    if not result.allocations:
        return _empty_breakdown_df()
    rows = [
        {
            "symbol": a.symbol,
            "strategy": a.strategy_name,
            "trades": a.total_trades,
            "win_rate_pct": round(float(a.win_rate) * 100, 1),
            "realized_pnl": round(float(a.realized_pnl), 2),
            "best_trade": round(float(a.best_trade), 2),
            "worst_trade": round(float(a.worst_trade), 2),
        }
        for a in result.allocations
    ]
    return pd.DataFrame(rows)


def _empty_trades_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "opened_at",
            "closed_at",
            "symbol",
            "side",
            "quantity",
            "entry_price",
            "exit_price",
            "realized_pnl",
        ]
    )


def _trades_dataframe(result: PortfolioBacktestResult) -> pd.DataFrame:
    if not result.trades:
        return _empty_trades_df()
    rows = [
        {
            "opened_at": pos.opened_datetime,
            "closed_at": pos.closed_datetime,
            "symbol": pos.symbol,
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


_INTRO = (
    "Define a portfolio of ``(symbol, strategy, params)`` allocations. "
    "All allocations share one cash pool, one timeframe, and one risk "
    "validator — so the backtest reflects realistic multi-pair trading "
    "rather than N independent single-pair runs.\n\n"
    "Edit the YAML directly, save it under ``data/portfolios/``, then "
    "run the aggregate backtest. The breakdown table shows which pair "
    "contributed how much realised P&L."
)


def render() -> None:
    """Render the Portfolio tab UI inside an enclosing :class:`gr.Tabs`."""
    initial_choices = _portfolio_choices()
    initial_value = initial_choices[0] if initial_choices else None
    initial_yaml = ""
    if initial_value is not None:
        try:
            initial_yaml = dump_yaml(load_portfolio(initial_value))
        except (FileNotFoundError, ValueError):
            initial_yaml = dump_yaml(example_portfolio())
    else:
        initial_yaml = dump_yaml(example_portfolio())

    with gr.Tab("Portfolio"):
        gr.Markdown(_INTRO)

        with gr.Row():
            portfolio_dropdown = gr.Dropdown(
                choices=initial_choices,
                value=initial_value,
                label="Saved portfolios",
                allow_custom_value=False,
            )
            refresh_btn = gr.Button("Refresh", variant="secondary")
            new_btn = gr.Button("New (example)", variant="secondary")
            delete_btn = gr.Button("Delete", variant="stop")

        editor = gr.Code(
            value=initial_yaml,
            language="yaml",
            label="Portfolio YAML (edit, then Save)",
            lines=18,
        )

        with gr.Row():
            save_btn = gr.Button("Save to disk", variant="secondary")
            start_input = gr.Textbox(value="2024-01-01", label="Start (YYYY-MM-DD)")
            end_input = gr.Textbox(value="", label="End (YYYY-MM-DD, blank = now)")

        with gr.Row():
            run_btn = gr.Button("Run portfolio backtest", variant="primary")
            clear_log_btn = gr.Button("Clear log")

        gr.Markdown("### Aggregate result")
        summary_output = gr.Markdown(value="_Run a backtest to see the summary here._")
        equity_output = gr.Plot(label="Portfolio equity curve")

        gr.Markdown("### Per-allocation breakdown")
        breakdown_output = gr.Dataframe(value=_empty_breakdown_df(), label="By symbol")

        gr.Markdown("### Closed trades (every allocation)")
        trades_output = gr.Dataframe(value=_empty_trades_df(), label="Closed trades")

        gr.Markdown("### Terminal")
        terminal = gr.Markdown(value=_render_terminal())

        # ------------------------------------------------------------------
        # Wiring
        # ------------------------------------------------------------------

        refresh_btn.click(
            fn=refresh_portfolios,
            inputs=[portfolio_dropdown],
            outputs=[portfolio_dropdown, terminal],
        )

        portfolio_dropdown.change(
            fn=load_portfolio_yaml,
            inputs=[portfolio_dropdown],
            outputs=[editor, terminal],
        )

        new_btn.click(
            fn=new_portfolio_yaml,
            inputs=[],
            outputs=[editor, terminal],
        )

        save_btn.click(
            fn=save_portfolio_yaml,
            inputs=[editor],
            outputs=[portfolio_dropdown, terminal],
        )

        delete_btn.click(
            fn=delete_portfolio_handler,
            inputs=[portfolio_dropdown],
            outputs=[portfolio_dropdown, editor, terminal],
        )

        run_btn.click(
            fn=run_portfolio_backtest,
            inputs=[editor, start_input, end_input],
            outputs=[summary_output, terminal, equity_output, breakdown_output, trades_output],
        )

        clear_log_btn.click(fn=clear_log, inputs=[], outputs=[terminal])
