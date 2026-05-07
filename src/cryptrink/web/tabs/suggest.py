"""Suggest tab for the Cryptrink Gradio web app."""

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
from cryptrink.web.state import default_symbol, get_runtime, get_symbol_choices


async def run_suggest(strategy_name: str, symbol: str) -> dict[str, object]:
    """Generate a single trade suggestion for the latest stored candle."""
    if not strategy_name:
        raise gr.Error("Select a strategy.")
    if not symbol:
        raise gr.Error("Enter a symbol.")

    try:
        strategy = resolve_strategy(strategy_name)
    except KeyError as exc:
        raise gr.Error(f"Unknown strategy '{strategy_name}'.") from exc

    runtime = get_runtime()
    session_factory = runtime.session_factory
    db_engine = session_factory.kw["bind"]
    async with db_engine.begin() as conn:
        await conn.run_sync(OHLCVModel.metadata.create_all)

    repository = OHLCVRepository(session_factory)
    data_feed = HistoricalDataFeed(repository)

    candles = await data_feed.get_ohlcv(
        symbol=symbol,
        timeframe=strategy.timeframe,
        limit=max(strategy.required_history + 10, 100),
    )

    if not candles:
        raise gr.Error(f"No historical data for {symbol} {strategy.timeframe}. Load OHLCV first.")

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


def render() -> None:
    """Render the Suggest tab UI inside an enclosing :class:`gr.Tabs`."""
    runtime = get_runtime()
    strategy_options = strategy_registry.list_strategies()
    default_strategy = (
        runtime.settings.default_strategy
        if runtime.settings.default_strategy in strategy_options
        else (strategy_options[0] if strategy_options else None)
    )
    with gr.Tab("Suggest"):
        gr.Markdown(
            "Generate a one-shot trade suggestion from the latest stored candle. "
            "No order is placed."
        )
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
        run_btn = gr.Button("Suggest", variant="primary")
        result_output = gr.JSON(label="Suggestion")

        run_btn.click(
            fn=run_suggest,
            inputs=[strategy_input, symbol_input],
            outputs=[result_output],
        )
