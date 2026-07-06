"""Portfolio screen for the Cryptrink workspace UI.

A two-stage pipeline:

1. **Compose & backtest** — build a multi-pair portfolio sharing one cash pool and
   backtest the whole allocation in one run. Allocations are edited as YAML (the
   source of truth on disk under ``data/portfolios/``); the run streams an interactive
   aggregate equity curve, a 4-up metrics row, and a per-allocation breakdown table.
2. **Tune a pair** — the single-pair backtest + optimizer folds in here; ``Add pair to
   portfolio`` upserts the tuned ``(symbol, strategy, params)`` into the Allocations
   above (see :func:`upsert_allocation_yaml`), so you never hand-copy tuned numbers.

Activity is pushed to the shared docked terminal via
:func:`cryptrink.web.state.log_event` rather than a per-screen log box.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import gradio as gr
import pandas as pd

from cryptrink.data.feed import HistoricalDataFeed
from cryptrink.data.storage import OHLCV as OHLCVModel
from cryptrink.data.storage import OHLCVRepository
from cryptrink.execution.models import Position
from cryptrink.portfolio.engine import PortfolioBacktestEngine
from cryptrink.portfolio.models import (
    Allocation,
    Portfolio,
    dump_yaml,
    example_portfolio,
    load_yaml,
)
from cryptrink.portfolio.storage import (
    delete_portfolio,
    list_portfolio_names,
    load_portfolio,
    save_portfolio,
)
from cryptrink.web import charts, components
from cryptrink.web.state import Dataset, get_runtime, log_event
from cryptrink.web.tabs import backtest
from cryptrink.web.tabs.backtest_tuning import decode_manual_params

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import plotly.graph_objects as go  # type: ignore[import-untyped]

    from cryptrink.portfolio.result import PortfolioBacktestResult


def _format_elapsed(start_perf: float) -> str:
    elapsed = time.perf_counter() - start_perf
    if elapsed < 1:
        return f"{elapsed * 1000:.0f}ms"
    return f"{elapsed:.2f}s"


# ----------------------------------------------------------------------
# YAML editor handlers (log to the shared terminal; return component updates)
# ----------------------------------------------------------------------


def _portfolio_choices() -> list[str]:
    return list_portfolio_names()


def load_portfolio_yaml(name: str | None) -> str:
    """Load YAML from disk into the editor."""
    if not name:
        return ""
    try:
        portfolio = load_portfolio(name)
    except (FileNotFoundError, ValueError) as exc:
        log_event("portfolio", "err", f"load {name!r} failed: {exc}")
        return ""
    log_event("portfolio", "info", f"loaded {name!r} from disk")
    return dump_yaml(portfolio)


def new_portfolio_yaml() -> str:
    """Reset the editor to the example portfolio."""
    log_event("portfolio", "info", "editor seeded with example portfolio")
    return dump_yaml(example_portfolio())


def save_portfolio_yaml(yaml_text: str) -> object:
    """Parse the editor, validate, and write to disk under the portfolio's own name."""
    try:
        portfolio = load_yaml(yaml_text)
    except Exception as exc:  # operator-facing: surface any YAML/parse error
        log_event("portfolio", "err", f"YAML failed to parse: {exc}")
        return gr.update()
    try:
        path = save_portfolio(portfolio)
    except ValueError as exc:
        log_event("portfolio", "err", f"validation failed: {exc}")
        return gr.update()
    log_event("portfolio", "ok", f"saved {portfolio.name!r} → {path}")
    return gr.update(choices=_portfolio_choices(), value=portfolio.name)


def delete_portfolio_handler(name: str | None) -> tuple[object, str]:
    if not name:
        return gr.update(), ""
    if not delete_portfolio(name):
        log_event("portfolio", "err", f"{name!r} not found on disk")
        return gr.update(), ""
    names = _portfolio_choices()
    new_value = names[0] if names else None
    log_event("portfolio", "info", f"deleted {name!r}")
    return gr.update(choices=names, value=new_value), ""


# ----------------------------------------------------------------------
# Add-pair-to-portfolio (connects the per-pair tuner to the portfolio)
# ----------------------------------------------------------------------


def upsert_allocation_yaml(
    yaml_text: str,
    symbol: str,
    timeframe: str,
    strategy_name: str,
    params: dict[str, float | int],
) -> tuple[str, str | None]:
    """Upsert one ``(symbol, strategy, params)`` allocation into a portfolio YAML.

    Pure and side-effect free so it can be unit-tested without Gradio. Returns
    ``(yaml, error)``: on success ``error`` is ``None`` and ``yaml`` is the updated
    document; on failure ``yaml`` is the unchanged input and ``error`` is an
    operator-facing message.

    Rules:
    * Blank editor → start a fresh portfolio that adopts the pair's ``timeframe``.
    * A portfolio uses a single timeframe: if it already has allocations on a
      different timeframe, adding a pair on another timeframe is rejected.
    * One allocation per symbol (mirrors ``Portfolio.validate``): an existing
      allocation for the same symbol is replaced, otherwise the pair is appended.
    """
    text = yaml_text.strip()
    if not text:
        portfolio = Portfolio(
            name="new",
            timeframe=timeframe,
            initial_balance=Decimal("10000"),
            allocations=[],
        )
    else:
        try:
            portfolio = load_yaml(yaml_text)
        except Exception as exc:  # operator-facing: surface any YAML/parse error
            return yaml_text, f"portfolio YAML failed to parse: {exc}"

    if portfolio.allocations and portfolio.timeframe != timeframe:
        return yaml_text, (
            f"pair timeframe {timeframe!r} does not match the portfolio's "
            f"{portfolio.timeframe!r}. A portfolio trades one timeframe — start a new "
            "portfolio (+ New) to use a different one."
        )
    if not portfolio.allocations:
        portfolio.timeframe = timeframe

    allocation = Allocation(symbol=symbol, strategy_name=strategy_name, params=dict(params))
    for i, existing in enumerate(portfolio.allocations):
        if existing.symbol == symbol:
            portfolio.allocations[i] = allocation
            break
    else:
        portfolio.allocations.append(allocation)

    return dump_yaml(portfolio), None


# ----------------------------------------------------------------------
# Run handler (streaming)
# ----------------------------------------------------------------------


async def run_portfolio_backtest(
    yaml_text: str,
    start_date: str,
    end_date: str,
) -> AsyncIterator[tuple[str, go.Figure | None, pd.DataFrame, pd.DataFrame]]:
    """Stream a portfolio backtest run.

    Yields ``(metrics_html, equity_fig, breakdown_df, trades_df)``. Every yield is
    a complete render so Gradio updates incrementally; log lines go to the shared
    docked terminal.
    """
    metrics_html = _empty_metrics_html()
    equity_fig: go.Figure | None = None
    breakdown_df = _empty_breakdown_df()
    trades_df = _empty_trades_df()
    empty = (metrics_html, equity_fig, breakdown_df, trades_df)

    log_event("portfolio", "info", "backtest: starting")
    yield empty

    try:
        portfolio = load_yaml(yaml_text)
    except Exception as exc:  # operator-facing: any parse error
        log_event("portfolio", "err", f"YAML failed to parse: {exc}")
        return

    errors = portfolio.validate()
    if errors:
        log_event("portfolio", "err", "invalid config — " + "; ".join(errors))
        return

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
        end_dt = (
            datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
            if end_date
            else datetime.now(UTC)
        )
    except ValueError as exc:
        log_event("portfolio", "err", f"invalid date: {exc}")
        return
    if end_dt <= start_dt:
        log_event("portfolio", "err", "end date must be after start date")
        return

    runtime = get_runtime()
    session_factory = runtime.session_factory
    db_engine = session_factory.kw["bind"]
    async with db_engine.begin() as conn:
        await conn.run_sync(OHLCVModel.metadata.create_all)
        await conn.run_sync(Position.metadata.create_all)

    log_event(
        "portfolio",
        "info",
        f"{portfolio.name!r} @ {portfolio.timeframe} — "
        f"{len(portfolio.enabled_allocations())} allocations, "
        f"capital=€{portfolio.initial_balance:,.2f}, "
        f"window={start_dt.date()} → {end_dt.date()}",
    )

    repository = OHLCVRepository(session_factory)
    data_feed = HistoricalDataFeed(repository)
    engine = PortfolioBacktestEngine(
        portfolio=portfolio,
        data_feed=data_feed,
        session_factory=session_factory,
        risk_settings=runtime.settings.risk,
    )
    log_event("portfolio", "info", "engine built — running event-driven replay…")

    started = time.perf_counter()
    try:
        result = await engine.run(start_time=start_dt, end_time=end_dt)
    except Exception as exc:  # report engine failure, keep UI responsive
        log_event("portfolio", "err", f"backtest failed after {_format_elapsed(started)}: {exc}")
        return

    log_event("portfolio", "info", f"replay finished in {_format_elapsed(started)}")
    _log_signal_breakdown(engine.signal_counts)
    _log_result_summary(result)

    yield (
        _metrics_html(result),
        charts.equity_curve_figure(result.equity_curve),
        _breakdown_dataframe(result),
        _trades_dataframe(result),
    )


def _log_signal_breakdown(counts: dict[str, dict[str, int]]) -> None:
    if not counts:
        log_event("portfolio", "info", "signals: no allocations were called")
        return
    for symbol, hist in sorted(counts.items()):
        total = sum(hist.values())
        parts = ", ".join(f"{n} {name}" for name, n in sorted(hist.items()))
        log_event("portfolio", "info", f"signals {symbol}: {total} ({parts})")


def _log_result_summary(result: PortfolioBacktestResult) -> None:
    metrics = result.metrics
    log_event(
        "portfolio",
        "ok",
        f"COMPLETE — trades={metrics.total_trades}, "
        f"return={float(metrics.total_return_pct) * 100:+.2f}%, "
        f"sharpe={float(metrics.sharpe_ratio):.2f}, "
        f"final_equity=€{metrics.ending_equity:,.2f}",
    )


# ----------------------------------------------------------------------
# Output formatting
# ----------------------------------------------------------------------


def _empty_metrics_html() -> str:
    cards = "".join(
        components.metric_card(label, "—", "")
        for label in ("Total return", "Sharpe", "Max drawdown", "Win rate")
    )
    return f'<div class="ck-metrics">{cards}</div>'


def _metrics_html(result: PortfolioBacktestResult) -> str:
    m = result.metrics
    ret_pct = float(m.total_return_pct) * 100
    cards = "".join(
        [
            components.metric_card(
                "Total return",
                f"{ret_pct:+.2f}%",
                f"€{m.total_return:,.0f}",
                "pos" if ret_pct >= 0 else "neg",
            ),
            components.metric_card("Sharpe", f"{float(m.sharpe_ratio):.2f}", "annualised"),
            components.metric_card(
                "Max drawdown", f"{float(m.max_drawdown) * 100:.1f}%", "peak to trough", "neg"
            ),
            components.metric_card(
                "Win rate", f"{float(m.win_rate) * 100:.1f}%", f"{m.total_trades} trades"
            ),
        ]
    )
    return f'<div class="ck-metrics">{cards}</div>'


def _empty_breakdown_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["symbol", "strategy", "trades", "win_rate_pct", "realized_pnl"])


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


def render() -> None:
    """Render the Portfolio screen panel inside the workspace shell."""
    initial_choices = _portfolio_choices()
    initial_value = initial_choices[0] if initial_choices else None
    if initial_value is not None:
        try:
            initial_yaml = dump_yaml(load_portfolio(initial_value))
        except (FileNotFoundError, ValueError):
            initial_yaml = dump_yaml(example_portfolio())
    else:
        initial_yaml = dump_yaml(example_portfolio())

    # ---- Stage 1: compose the portfolio + backtest it (the workbench) ----
    gr.HTML('<div class="ck-section-label">1 · Compose &amp; backtest your portfolio</div>')
    with gr.Row(elem_classes=["ck-screen-cols"]):
        # left: portfolio picker + allocations editor
        with gr.Column(scale=0, elem_classes=["ck-col-300"]):
            with gr.Group(elem_classes=["ck-card"]):
                gr.HTML('<div class="ck-section-label">Portfolios</div>')
                portfolio_dropdown = gr.Dropdown(
                    choices=initial_choices,
                    value=initial_value,
                    label="Saved portfolios",
                    allow_custom_value=False,
                )
                with gr.Row():
                    new_btn = gr.Button("+ New", elem_classes=["ck-btn-secondary"])
                    delete_btn = gr.Button("Delete", elem_classes=["ck-btn-secondary"])

            with gr.Group(elem_classes=["ck-card"]):
                gr.HTML('<div class="ck-section-label">Allocations (YAML)</div>')
                gr.Markdown(
                    "One allocation per pair. Add pairs from **Tune a pair** below, or "
                    "edit this YAML directly."
                )
                editor = gr.Code(value=initial_yaml, language="yaml", lines=16)
                save_btn = gr.Button("Save to disk", elem_classes=["ck-btn-secondary"])
                with gr.Row():
                    start_input = gr.Textbox(value="2024-01-01", label="Start (YYYY-MM-DD)")
                    end_input = gr.Textbox(value="", label="End (blank = now)")
                run_btn = gr.Button("Run backtest", elem_classes=["ck-btn-primary"])

        # right: portfolio backtest results
        with gr.Column(elem_classes=["ck-col-main"]):
            metrics_output = gr.HTML(_empty_metrics_html())
            with gr.Group(elem_classes=["ck-card"]):
                gr.HTML('<div class="ck-card-title">Aggregate equity curve</div>')
                equity_output = gr.Plot(elem_classes=["ck-plot"])
            with gr.Group(elem_classes=["ck-card"]):
                gr.HTML('<div class="ck-card-title">Per-allocation breakdown</div>')
                breakdown_output = gr.Dataframe(value=_empty_breakdown_df())
            with gr.Accordion("Closed trades", open=False):
                trades_output = gr.Dataframe(value=_empty_trades_df())

    # ---- Stage 2: tune one pair's strategy, then add it to the portfolio above ----
    gr.HTML('<div class="ck-section-label">2 · Tune a pair, then add it to the portfolio</div>')
    with gr.Accordion("Tune a pair", open=False):
        gr.Markdown(
            "Pick a strategy and dataset, tune its parameters (by hand or with the "
            "optimizer), then **Add pair to portfolio** to drop it into the Allocations "
            "above. Repeat for each pair you want to trade. The portfolio uses a single "
            "timeframe — the first pair you add sets it."
        )
        add_pair_btn = gr.Button("Add pair to portfolio", elem_classes=["ck-btn-primary"])
        # The single-pair backtest + optimizer (also carrying Suggest). ``render`` returns
        # a handle to its strategy/dataset/param components so we can read the tuned pair.
        handle = backtest.render()

    # ---- wiring ----
    portfolio_dropdown.change(fn=load_portfolio_yaml, inputs=[portfolio_dropdown], outputs=[editor])
    new_btn.click(fn=new_portfolio_yaml, inputs=[], outputs=[editor])
    save_btn.click(fn=save_portfolio_yaml, inputs=[editor], outputs=[portfolio_dropdown])
    delete_btn.click(
        fn=delete_portfolio_handler,
        inputs=[portfolio_dropdown],
        outputs=[portfolio_dropdown, editor],
    )
    run_btn.click(
        fn=run_portfolio_backtest,
        inputs=[editor, start_input, end_input],
        outputs=[metrics_output, equity_output, breakdown_output, trades_output],
    )

    def _on_add_pair(
        yaml_text: str,
        strategy_name: str,
        dataset_value: str,
        *param_values: object,
    ) -> object:
        """Read the tuned pair from the Backtest section and upsert it into the editor."""
        if not strategy_name:
            log_event("portfolio", "err", "add pair: no strategy selected")
            return gr.update()
        if not dataset_value:
            log_event("portfolio", "err", "add pair: no dataset selected")
            return gr.update()
        try:
            symbol, timeframe = Dataset.parse(dataset_value)
        except ValueError:
            log_event("portfolio", "err", f"add pair: invalid dataset {dataset_value!r}")
            return gr.update()
        params = decode_manual_params(strategy_name, param_values, handle.manual_panels)
        new_yaml, error = upsert_allocation_yaml(
            yaml_text, symbol, timeframe, strategy_name, params
        )
        if error:
            log_event("portfolio", "err", f"add pair: {error}")
            return gr.update()
        log_event(
            "portfolio",
            "ok",
            f"add pair: {symbol} @ {timeframe} · {strategy_name} added to the portfolio",
        )
        return new_yaml

    add_pair_btn.click(
        fn=_on_add_pair,
        inputs=[editor, handle.strategy_input, handle.dataset_input, *handle.manual_components],
        outputs=[editor],
    )
