"""Suggest screen for the Cryptrink workspace UI.

Generates a one-shot trade suggestion against a stored OHLCV
``(symbol, timeframe)`` dataset and renders it as a BUY/SELL/HOLD verdict card.
No order is placed.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from decimal import Decimal

import gradio as gr

from cryptrink.data.feed import HistoricalDataFeed
from cryptrink.data.indicators import ohlcv_to_dataframe
from cryptrink.data.storage import OHLCV as OHLCVModel
from cryptrink.data.storage import OHLCVRepository
from cryptrink.execution.base import ExecutionContext
from cryptrink.execution.suggest import SuggestExecutor
from cryptrink.runtime import resolve_strategy
from cryptrink.strategies import registry as strategy_registry
from cryptrink.strategies.base import StrategyContext
from cryptrink.web import components
from cryptrink.web.state import (
    Dataset,
    dataset_choices,
    dataset_choices_sync,
    get_runtime,
    select_dataset_value,
)

# ----------------------------------------------------------------------
# Dataset dropdown plumbing (per-tab; see backtest.py for the rationale)
# ----------------------------------------------------------------------


async def refresh_datasets(current: str | None) -> object:
    """Re-query the OHLCV table and update this tab's Dataset dropdown."""
    choices = await dataset_choices()
    return gr.update(choices=choices, value=select_dataset_value(current, choices))


# ----------------------------------------------------------------------
# Run handler
# ----------------------------------------------------------------------


async def run_suggest(strategy_name: str, dataset_value: str | None) -> dict[str, object]:
    """Generate a single trade suggestion for the latest stored candle."""
    if not strategy_name:
        raise gr.Error("Select a strategy.")
    if not dataset_value:
        raise gr.Error(
            "Select a dataset. Open the Data tab and run Backfill if the "
            "dropdown is empty, then click Refresh datasets here."
        )
    try:
        symbol, timeframe = Dataset.parse(dataset_value)
    except ValueError as exc:
        raise gr.Error(f"Malformed dataset value: {exc}") from exc

    try:
        strategy = resolve_strategy(strategy_name)
    except KeyError as exc:
        raise gr.Error(f"Unknown strategy '{strategy_name}'.") from exc

    if strategy.timeframe != timeframe:
        # The strategy declares a preferred timeframe but the dataset is
        # different. We honour the operator's selection because all
        # generate_signal does is compute over the candles in context.
        # No exception — just informational; the suggestion JSON includes
        # the actual timeframe used.
        pass

    runtime = get_runtime()
    session_factory = runtime.session_factory
    db_engine = session_factory.kw["bind"]
    async with db_engine.begin() as conn:
        await conn.run_sync(OHLCVModel.metadata.create_all)

    repository = OHLCVRepository(session_factory)
    data_feed = HistoricalDataFeed(repository)

    candles = await data_feed.get_ohlcv(
        symbol=symbol,
        timeframe=timeframe,
        limit=max(strategy.required_history + 10, 100),
    )

    if not candles:
        raise gr.Error(
            f"No historical data for {symbol} {timeframe}. "
            "Open the Data tab and run Backfill first."
        )

    ohlcv_df = ohlcv_to_dataframe(candles)
    current_price = Decimal(str(ohlcv_df.iloc[-1]["close"]))
    last_index = ohlcv_df.index[-1]
    timestamp = (
        last_index.to_pydatetime() if hasattr(last_index, "to_pydatetime") else datetime.now(UTC)
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

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "strategy": strategy.name,
        "timestamp": timestamp.isoformat(),
        "signal_type": signal.signal_type.value,
        "signal_strength": signal.strength.value,
        "current_price": str(current_price),
        "candles_used": len(candles),
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


# ----------------------------------------------------------------------
# Verdict card rendering
# ----------------------------------------------------------------------


def _verdict(signal_type: str) -> tuple[str, str]:
    """Map a raw signal-type value to a (label, tone) verdict."""
    value = signal_type.lower()
    if "long" in value or value == "buy":
        return "BUY", "pos"
    if "short" in value or value == "sell":
        return "SELL", "neg"
    return "HOLD", "dim"


def suggestion_card_html(result: dict[str, object]) -> str:
    """Render the suggestion result as a verdict card."""
    label, tone = _verdict(str(result.get("signal_type", "")))
    tone_cls = components.TONE_CLASS.get(tone, "")
    rows = [
        ("Symbol", str(result.get("symbol", "—"))),
        ("Timeframe", str(result.get("timeframe", "—"))),
        ("Signal", str(result.get("signal_type", "—"))),
        ("Strength", str(result.get("signal_strength", "—"))),
        ("Current price", f"€{result.get('current_price', '—')}"),
        ("Candles used", str(result.get("candles_used", "—"))),
    ]
    grid = "".join(components.kv_row(k, v) for k, v in rows)
    badge = html.escape(str(result.get("signal_strength", "")))
    return (
        '<div class="ck-card">'
        '<div style="display:flex;align-items:center;gap:14px;margin-bottom:14px">'
        f'<span class="ck-verdict {tone_cls}">{label}</span>'
        f'<span class="ck-badge" style="background:var(--surface2)">{badge}</span></div>'
        f"{grid}</div>"
    )


async def suggest_and_render(strategy_name: str, dataset_value: str | None) -> str:
    """Run a suggestion and render it as a verdict card (errors surface as gr.Error)."""
    result = await run_suggest(strategy_name, dataset_value)
    return suggestion_card_html(result)


# ----------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------


def render_section() -> None:
    """Render the Suggest tool as a stacked section (folded into the Backtest screen).

    Suggest no longer owns a sidebar screen; :func:`cryptrink.web.tabs.backtest.render`
    calls this after the backtest layout so the one-shot suggestion lives alongside the
    full backtest, which shares the same strategy + dataset inputs conceptually.
    """
    runtime = get_runtime()
    strategy_options = strategy_registry.list_strategies()
    default_strategy = (
        runtime.settings.default_strategy
        if runtime.settings.default_strategy in strategy_options
        else (strategy_options[0] if strategy_options else None)
    )
    initial_choices = dataset_choices_sync()
    initial_value = initial_choices[0][1] if initial_choices else None

    with gr.Column(elem_classes=["ck-col-main"]):
        gr.HTML(
            '<div class="ck-section-label" style="margin-top:6px">'
            "Suggest — one-shot trade suggestion from the latest candle (no order placed)"
            "</div>"
        )
        with gr.Group(elem_classes=["ck-card"]), gr.Row():
            strategy_input = gr.Dropdown(
                choices=strategy_options, value=default_strategy, label="Strategy"
            )
            # Pre-populate synchronously + allow_custom_value=True (Gradio SSR
            # rejects otherwise-valid values when server-side choices is empty).
            dataset_input = gr.Dropdown(
                choices=initial_choices,
                value=initial_value,
                label="Dataset (symbol @ timeframe)",
                allow_custom_value=True,
            )
            run_btn = gr.Button("Suggest", elem_classes=["ck-btn-primary"])
        result_output = gr.HTML()

    dataset_input.focus(fn=refresh_datasets, inputs=[dataset_input], outputs=[dataset_input])
    run_btn.click(
        fn=suggest_and_render,
        inputs=[strategy_input, dataset_input],
        outputs=[result_output],
    )
