"""Live tab for the Cryptrink Gradio web app.

Drives a strategy on a periodic interval via :class:`LiveLoop`. The tab
is paper-mode by default — every Start click instantiates a fresh
:class:`PaperExecutor` against the configured database. Switching to a
live exchange happens in a follow-up that wires :class:`LiveExecutor`
behind the same Start button when ``REVOLUTX_API_KEY`` is present.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import gradio as gr

from cryptrink.cli.utils import init_db_schema
from cryptrink.data.feed import HistoricalDataFeed
from cryptrink.data.storage import OHLCVRepository
from cryptrink.execution.engine import TradingEngine
from cryptrink.execution.paper import PaperExecutor
from cryptrink.runtime import resolve_strategy
from cryptrink.strategies import registry as strategy_registry
from cryptrink.web.live_loop import (
    LiveLoop,
    LiveLoopState,
    get_active_loop,
    set_active_loop,
)
from cryptrink.web.state import get_runtime


async def start_loop(
    strategy_name: str,
    symbol: str,
    interval_seconds: float,
    initial_balance: float,
) -> str:
    """Build a fresh :class:`LiveLoop` and start it. Used by the Start button."""
    if not strategy_name:
        raise gr.Error("Select a strategy.")
    if not symbol:
        raise gr.Error("Enter a symbol.")
    if interval_seconds <= 0:
        raise gr.Error("Interval must be positive.")

    existing = get_active_loop()
    if existing is not None and existing.is_running:
        raise gr.Error("A live loop is already running. Stop it first before starting a new one.")

    try:
        strategy = resolve_strategy(strategy_name)
    except KeyError as exc:
        raise gr.Error(f"Unknown strategy '{strategy_name}'.") from exc

    runtime = get_runtime()
    session_factory = runtime.session_factory
    await init_db_schema(session_factory)

    repository = OHLCVRepository(session_factory)
    data_feed = HistoricalDataFeed(repository)

    executor = PaperExecutor(initial_balance=Decimal(str(initial_balance)))
    engine = TradingEngine(
        strategy=strategy,
        executor=executor,
        session_factory=session_factory,
        initial_balance=Decimal(str(initial_balance)),
        risk_settings=runtime.settings.risk,
    )
    await engine.start()

    loop = LiveLoop(
        engine=engine,
        strategy=strategy,
        symbol=symbol,
        data_feed=data_feed,
        interval_seconds=float(interval_seconds),
    )
    set_active_loop(loop)
    await loop.start()

    return _render_status(loop.snapshot(), engine_id=engine.engine_id)


async def stop_loop() -> str:
    """Signal the running loop to stop and await termination."""
    loop = get_active_loop()
    if loop is None:
        return _render_status(None)
    await loop.stop()
    return _render_status(loop.snapshot())


def refresh_status() -> str:
    """Read the latest snapshot of the active loop."""
    loop = get_active_loop()
    if loop is None:
        return _render_status(None)
    return _render_status(loop.snapshot())


def _render_status(state: LiveLoopState | None, *, engine_id: str | None = None) -> str:
    """Format a :class:`LiveLoopState` into a markdown status block."""
    if state is None:
        return "_No live loop has been started._"

    rows: list[tuple[str, str]] = [
        ("Status", "🟢 Running" if state.running else "⏹ Stopped"),
        ("Symbol", state.symbol or "—"),
        ("Strategy", state.strategy_name or "—"),
        ("Interval", f"{state.interval_seconds:.0f}s"),
    ]
    if engine_id is not None:
        rows.append(("Engine ID", f"`{engine_id}`"))
    if state.started_at is not None:
        rows.append(("Started at", state.started_at.isoformat(timespec="seconds")))
    if state.stopped_at is not None and not state.running:
        rows.append(("Stopped at", state.stopped_at.isoformat(timespec="seconds")))
    if state.last_iteration_at is not None:
        rows.append(("Last iteration", state.last_iteration_at.isoformat(timespec="seconds")))
    rows.append(("Iterations", str(state.iteration_count)))
    rows.append(("Signals", str(state.signal_count)))
    rows.append(("Executions", str(state.execution_count)))
    if state.last_signal_type is not None:
        last_sig = state.last_signal_at
        when = last_sig.isoformat(timespec="seconds") if last_sig is not None else "—"
        rows.append(("Last signal", f"{state.last_signal_type} at {when}"))
    if state.error_count > 0:
        rows.append(("Errors", str(state.error_count)))
    if state.last_error is not None:
        rows.append(("Last error", f"`{state.last_error}`"))

    body = "\n".join(f"| {label} | {value} |" for label, value in rows)
    return (
        f"_Last refreshed at {datetime.now(UTC).isoformat(timespec='seconds')}._\n\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        f"{body}\n"
    )


def render() -> None:
    """Render the Live tab UI inside an enclosing :class:`gr.Tabs`."""
    runtime = get_runtime()
    strategy_options = strategy_registry.list_strategies()
    default_strategy = (
        runtime.settings.default_strategy
        if runtime.settings.default_strategy in strategy_options
        else (strategy_options[0] if strategy_options else None)
    )
    default_symbol = runtime.settings.symbols[0] if runtime.settings.symbols else "BTC-EUR"

    with gr.Tab("Live"):
        gr.Markdown(
            "Run a strategy on a periodic interval. Each tick fetches the latest "
            "candle from the configured database, generates a signal, and routes it "
            "through risk validation and a **paper** executor. No real orders are "
            "placed. Live exchange wiring (Revolut X) lands in a follow-up commit on "
            "this branch."
        )
        with gr.Row():
            strategy_input = gr.Dropdown(
                choices=strategy_options,
                value=default_strategy,
                label="Strategy",
            )
            symbol_input = gr.Textbox(value=default_symbol, label="Symbol")
        with gr.Row():
            interval_input = gr.Number(value=60.0, label="Interval (seconds)", minimum=1)
            balance_input = gr.Number(value=10000.0, label="Initial paper balance (EUR)")

        with gr.Row():
            start_btn = gr.Button("Start", variant="primary")
            stop_btn = gr.Button("Stop", variant="stop")
            refresh_btn = gr.Button("Refresh")

        status_output = gr.Markdown(value=refresh_status())

        start_btn.click(
            fn=start_loop,
            inputs=[strategy_input, symbol_input, interval_input, balance_input],
            outputs=[status_output],
        )
        stop_btn.click(fn=stop_loop, inputs=[], outputs=[status_output])
        refresh_btn.click(fn=refresh_status, inputs=[], outputs=[status_output])
