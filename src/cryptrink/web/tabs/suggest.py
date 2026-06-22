"""Suggest tab for the Cryptrink Gradio web app.

Generates a one-shot trade suggestion against a stored OHLCV
``(symbol, timeframe)`` dataset — picked from the same DB-driven Dataset
dropdown the Backtest and Live tabs use, so all three tabs agree on what
"the data" is. Setting up the suggestion path on a timeframe the
database doesn't actually have produces an immediate, friendly error
rather than a silent empty result.
"""

from __future__ import annotations

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
from cryptrink.web.state import Dataset, get_runtime, list_datasets, list_datasets_sync

# ----------------------------------------------------------------------
# Dataset dropdown plumbing (per-tab; see backtest.py for the rationale)
# ----------------------------------------------------------------------


async def _dataset_choices() -> list[tuple[str, str]]:
    return [(ds.label, ds.value) for ds in await list_datasets()]


async def refresh_datasets(current: str | None) -> object:
    """Re-query the OHLCV table and update this tab's Dataset dropdown."""
    choices = await _dataset_choices()
    if not choices:
        return gr.update(choices=[], value=None)
    values = {value for _, value in choices}
    new_value = current if current in values else choices[0][1]
    return gr.update(choices=choices, value=new_value)


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
# Render
# ----------------------------------------------------------------------


def render() -> None:
    """Render the Suggest tab UI inside an enclosing :class:`gr.Tabs`."""
    runtime = get_runtime()
    strategy_options = strategy_registry.list_strategies()
    default_strategy = (
        runtime.settings.default_strategy
        if runtime.settings.default_strategy in strategy_options
        else (strategy_options[0] if strategy_options else None)
    )
    with gr.Column():
        gr.Markdown(
            "Generate a one-shot trade suggestion from the latest stored candle. "
            "No order is placed. The Dataset dropdown lists what is actually in "
            "the database — open the Data tab and run Backfill if it's empty, "
            "then click Refresh datasets here."
        )
        with gr.Row():
            strategy_input = gr.Dropdown(
                choices=strategy_options,
                value=default_strategy,
                label="Strategy",
            )
            # See backtest.py for why we pre-populate synchronously and
            # set allow_custom_value=True (Gradio SSR mode rejects
            # otherwise-valid values when server-side ``choices`` is empty
            # at render time, even after an async refresh).
            initial_datasets = list_datasets_sync()
            initial_choices = [(ds.label, ds.value) for ds in initial_datasets]
            initial_value = initial_choices[0][1] if initial_choices else None
            dataset_input = gr.Dropdown(
                choices=initial_choices,
                value=initial_value,
                label="Dataset (symbol @ timeframe)",
                allow_custom_value=True,
            )
            refresh_btn = gr.Button("Refresh datasets", variant="secondary")
        run_btn = gr.Button("Suggest", variant="primary")
        result_output = gr.JSON(label="Suggestion")

        refresh_btn.click(fn=refresh_datasets, inputs=[dataset_input], outputs=[dataset_input])
        dataset_input.focus(fn=refresh_datasets, inputs=[dataset_input], outputs=[dataset_input])
        run_btn.click(
            fn=run_suggest,
            inputs=[strategy_input, dataset_input],
            outputs=[result_output],
        )
