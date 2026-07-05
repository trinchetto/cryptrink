"""Live screen for the Cryptrink workspace UI.

Drives a strategy on a periodic interval via :class:`LiveLoop`. The active trading
mode is the global workspace mode (paper / live): paper replays signals against the
stored OHLCV; live builds a :class:`LiveExecutor` against Revolut X when credentials
are present, and silently falls back to paper otherwise so Start never accidentally
turns into real-money trading. Starting in live mode is gated by a browser confirm.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import gradio as gr

from cryptrink.cli.utils import init_db_schema
from cryptrink.data.feed import HistoricalDataFeed
from cryptrink.data.storage import OHLCVRepository
from cryptrink.runtime import resolve_strategy
from cryptrink.strategies import registry as strategy_registry
from cryptrink.strategies.base import SignalType
from cryptrink.web import charts, components
from cryptrink.web.live_loop import LiveLoop, LiveLoopState, get_active_loop, set_active_loop
from cryptrink.web.live_setup import LiveMode, build_live_components, has_revolutx_credentials
from cryptrink.web.screens import dashboard
from cryptrink.web.state import (
    Dataset,
    dataset_choices,
    dataset_choices_sync,
    get_active_screen,
    get_mode,
    get_runtime,
    log_event,
    select_dataset_value,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import plotly.graph_objects as go  # type: ignore[import-untyped]

    from cryptrink.execution.base import ExecutionResult
    from cryptrink.execution.repository import OrderRepository
    from cryptrink.notifications.discord import DiscordNotifier
    from cryptrink.strategies.base import Signal


def _build_discord_callback(
    notifier: DiscordNotifier,
    order_repo: OrderRepository,
) -> Callable[[Signal, ExecutionResult], Awaitable[None]]:
    """Wrap the discord notifier in an on_signal-shaped callback.

    Only successful executions that produced an ``order_id`` actually fire a Discord
    embed. HOLD signals and rejected executions are skipped silently.
    """

    async def callback(signal: Signal, result: ExecutionResult) -> None:
        if signal.signal_type == SignalType.HOLD:
            return
        if not result.success or result.order_id is None:
            return
        order = await order_repo.get_by_order_id(result.order_id)
        if order is None:
            return
        await notifier.send_trade_notification(order)

    return callback


async def test_discord() -> object:
    """Send a synthetic Discord embed via the configured webhook and surface the result.

    Bypasses the notifier's ``enabled`` flag (the operator explicitly asked to test) and
    reports the HTTP status/body so a misconfigured webhook is diagnosable rather than
    silently dropped. Also mirrors the outcome into the docked terminal.
    """
    from cryptrink.notifications.discord import DiscordNotifier

    notifications = get_runtime().settings.notifications
    webhook = notifications.discord_webhook_url.get_secret_value()
    notifier = DiscordNotifier(webhook, enabled=notifications.discord_enabled)
    result = await notifier.send_test()
    log_event("live", "ok" if result.ok else "err", f"Discord test: {result.detail}")
    icon = "✅" if result.ok else "⚠️"
    return gr.update(value=f"{icon} **Discord test** — {result.detail}", visible=True)


async def refresh_datasets(current: str | None) -> object:
    """Re-query the OHLCV table and update this screen's Dataset dropdown."""
    choices = await dataset_choices()
    return gr.update(choices=choices, value=select_dataset_value(current, choices))


async def _load_candles(dataset_value: str | None) -> list[dict[str, object]]:
    """Read recent stored OHLCV for the selected dataset as candlestick rows."""
    if not dataset_value:
        return []
    try:
        symbol, timeframe = Dataset.parse(dataset_value)
    except ValueError:
        return []
    runtime = get_runtime()
    feed = HistoricalDataFeed(OHLCVRepository(runtime.session_factory))
    try:
        rows = await feed.get_ohlcv(symbol, timeframe, limit=120)
    except Exception:  # the chart is best-effort; never break the screen on a read
        return []
    return [
        {
            "time": datetime.fromtimestamp(int(row["timestamp"]) / 1000, tz=UTC),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
        for row in rows
    ]


async def load_candle_chart(dataset_value: str | None) -> go.Figure:
    """Build the candlestick figure for the selected dataset."""
    return charts.candlestick_figure(await _load_candles(dataset_value))


async def start_loop(
    strategy_name: str,
    dataset_value: str | None,
    interval_seconds: float,
    initial_balance: float,
    heartbeat_enabled: bool,
    heartbeat_interval_seconds: float,
) -> tuple[str, str]:
    """Build a fresh :class:`LiveLoop` and start it. Used by the Start button.

    The requested mode is the global workspace mode; ``build_live_components`` falls
    back to paper when live is requested without credentials.
    """
    if not strategy_name:
        raise gr.Error("Select a strategy.")
    if not dataset_value:
        raise gr.Error(
            "Select a dataset. Open the Data screen and run Backfill if the dropdown is empty."
        )
    try:
        symbol, dataset_timeframe = Dataset.parse(dataset_value)
    except ValueError as exc:
        raise gr.Error(f"Malformed dataset value: {exc}") from exc
    if interval_seconds <= 0:
        raise gr.Error("Interval must be positive.")
    if heartbeat_enabled and heartbeat_interval_seconds <= 0:
        raise gr.Error("Heartbeat interval must be positive.")

    requested_mode = LiveMode(get_mode())

    existing = get_active_loop()
    if existing is not None and existing.is_running:
        raise gr.Error("A live loop is already running. Stop it first before starting a new one.")

    try:
        strategy = resolve_strategy(strategy_name)
    except KeyError as exc:
        raise gr.Error(f"Unknown strategy '{strategy_name}'.") from exc

    if strategy.timeframe != dataset_timeframe:
        raise gr.Error(
            f"Strategy {strategy.name!r} expects timeframe={strategy.timeframe!r} "
            f"but the selected dataset is {dataset_timeframe!r}. Pick a dataset that "
            f"matches the strategy's timeframe, or backfill {strategy.timeframe!r} "
            f"for {symbol} from the Data screen."
        )

    runtime = get_runtime()
    session_factory = runtime.session_factory
    await init_db_schema(session_factory)

    components = await build_live_components(
        settings=runtime.settings,
        session_factory=session_factory,
        strategy=strategy,
        requested_mode=requested_mode,
        initial_balance=Decimal(str(initial_balance)),
    )

    on_signal = None
    on_heartbeat = None
    heartbeat_arg: float | None = None
    if components.notifier is not None:
        from cryptrink.execution.repository import OrderRepository

        on_signal = _build_discord_callback(
            notifier=components.notifier,
            order_repo=OrderRepository(session_factory),
        )
        if heartbeat_enabled:
            on_heartbeat = components.notifier.send_heartbeat
            heartbeat_arg = float(heartbeat_interval_seconds)
    elif heartbeat_enabled:
        raise gr.Error(
            "Heartbeat requires Discord to be configured. Set "
            "NOTIFY_DISCORD_ENABLED=true and NOTIFY_DISCORD_WEBHOOK_URL "
            "in the Space secrets first."
        )

    loop = LiveLoop(
        engine=components.engine,
        strategy=strategy,
        symbol=symbol,
        data_feed=components.data_feed,
        interval_seconds=float(interval_seconds),
        on_signal=on_signal,
        on_stop=components.cleanup,
        on_heartbeat=on_heartbeat,
        heartbeat_interval_seconds=heartbeat_arg,
    )
    set_active_loop(loop)
    await loop.start()

    log_event(
        "live",
        "warn" if components.mode == LiveMode.LIVE else "ok",
        f"loop started in {components.mode.value.upper()} mode · {symbol} · "
        f"{float(interval_seconds):.0f}s",
    )
    snapshot = loop.snapshot()
    return (
        _activity_html(snapshot),
        _status_html(
            snapshot,
            engine_id=components.engine.engine_id,
            mode=components.mode,
            requested_mode=requested_mode,
        ),
    )


async def stop_loop() -> tuple[str, str]:
    """Signal the running loop to stop and await termination."""
    loop = get_active_loop()
    if loop is None:
        return _activity_html(None), _status_html(None)
    await loop.stop()
    log_event("live", "info", "loop stopped by operator")
    snapshot = loop.snapshot()
    return _activity_html(snapshot), _status_html(snapshot)


def refresh_status() -> tuple[str, str]:
    """Read the latest snapshot of the active loop."""
    loop = get_active_loop()
    if loop is None:
        return _activity_html(None), _status_html(None)
    snapshot = loop.snapshot()
    return _activity_html(snapshot), _status_html(snapshot)


# ----------------------------------------------------------------------
# Status / activity rendering
# ----------------------------------------------------------------------


def _activity_html(state: LiveLoopState | None) -> str:
    if state is None:
        pairs = [("Iterations", "0"), ("Signals", "0"), ("Executions", "0"), ("Errors", "0")]
    else:
        pairs = [
            ("Iterations", str(state.iteration_count)),
            ("Signals", str(state.signal_count)),
            ("Executions", str(state.execution_count)),
            ("Errors", str(state.error_count)),
        ]
    cells = "".join(components.stat_cell(label, value) for label, value in pairs)
    return (
        '<div class="ck-card"><div class="ck-card-title">Loop activity</div>'
        f'<div class="ck-stats-row">{cells}</div></div>'
    )


def _status_html(
    state: LiveLoopState | None,
    *,
    engine_id: str | None = None,
    mode: LiveMode | None = None,
    requested_mode: LiveMode | None = None,
) -> str:
    running = bool(state and state.running)
    pill = (
        '<span class="ck-pill-run">Running</span>'
        if running
        else '<span class="ck-pill-idle">Idle</span>'
    )
    if state is None:
        rows = components.kv_row("Status", "No loop started")
    else:
        mode_text = "—"
        if mode is not None:
            mode_text = mode.value
            if requested_mode is not None and requested_mode != mode:
                mode_text += f" (requested {requested_mode.value}, fell back)"
        last_sig = "—"
        if state.last_signal_type is not None:
            when = (
                state.last_signal_at.isoformat(timespec="seconds")
                if state.last_signal_at is not None
                else "—"
            )
            last_sig = f"{state.last_signal_type} at {when}"
        rows = "".join(
            [
                components.kv_row("Symbol", state.symbol or "—"),
                components.kv_row("Strategy", state.strategy_name or "—"),
                components.kv_row("Interval", f"{state.interval_seconds:.0f}s"),
                components.kv_row("Mode", mode_text),
                components.kv_row("Engine ID", engine_id or "—"),
                components.kv_row("Last signal", last_sig),
            ]
        )
        if state.last_error:
            rows += components.kv_row("Last error", state.last_error)
    return (
        '<div class="ck-card"><div style="display:flex;justify-content:space-between;'
        'align-items:center;margin-bottom:10px">'
        '<span class="ck-section-label">Loop status</span>'
        f"{pill}</div>{rows}</div>"
    )


# ----------------------------------------------------------------------
# Diagnostics handlers (Discord / connection / pre-flight)
# ----------------------------------------------------------------------


async def preflight_order(dataset_value: str | None, initial_balance: float) -> str:
    """Look up Revolut X pair limits and check the planned order would clear them."""
    if not dataset_value:
        return "_Pick a dataset first._"
    try:
        symbol, _ = Dataset.parse(dataset_value)
    except ValueError as exc:
        return f"_Malformed dataset value: {exc}_"

    runtime = get_runtime()
    if not has_revolutx_credentials(runtime.settings):
        return (
            "**Revolut X credentials missing.** Pre-flight needs the live API to "
            "fetch per-pair limits — set `REVOLUTX_API_KEY` and "
            "`REVOLUTX_PRIVATE_KEY` first."
        )

    from cryptrink.exchange.revolutx import RevolutXExchange

    try:
        exchange = RevolutXExchange.from_settings(runtime.settings.revolutx)
    except ValueError as exc:
        return f"❌ **Failed to load private key:** {exc}"

    try:
        await exchange.connect()
        try:
            pair_infos = await exchange.get_pair_infos()
        except Exception as exc:
            return f"❌ **`/configuration/pairs` call failed:** {type(exc).__name__}: {exc}"

        info = pair_infos.get(symbol)
        if info is None:
            return (
                f"❌ **Pair `{symbol}` not found on Revolut X.** Available pairs: "
                f"{', '.join(sorted(pair_infos.keys())[:10])}{'…' if len(pair_infos) > 10 else ''}"
            )

        try:
            ticker = await exchange.get_ticker(symbol)
            current_price = ticker.last
        except Exception as exc:
            return f"❌ **Couldn't fetch current price for {symbol}:** {exc}"
    finally:
        with contextlib.suppress(Exception):
            await exchange.close()

    risk = runtime.settings.risk
    max_pct = Decimal(str(risk.max_position_size_pct))
    balance = Decimal(str(initial_balance))
    notional = balance * max_pct
    if current_price <= 0:
        return f"❌ **Invalid current price** ({current_price}) for {symbol}."
    quantity = notional / current_price

    rows = [
        ("Symbol", info.symbol),
        ("Current price", f"{current_price} {info.quote}"),
        ("Planned allocation", f"≈ {notional} {info.quote}"),
        ("Planned quantity", f"≈ {quantity} {info.base}"),
        ("min_order_size", f"{info.min_order_size} {info.base}"),
        ("min_order_size_quote", f"{info.min_order_size_quote} {info.quote}"),
    ]
    body = "\n".join(f"| {label} | {value} |" for label, value in rows)
    table = "| Field | Value |\n| --- | --- |\n" + body

    reason = info.reject_reason(quantity=quantity, notional=notional)
    if reason is None:
        verdict = f"✅ **Order would clear all minimums** for `{symbol}`."
    else:
        verdict = (
            f"❌ **Order would be rejected:** {reason}.\n\n"
            "Raise `RISK_MAX_POSITION_SIZE_PCT`, pick a lower-priced pair, or top up "
            f"the {info.quote} balance."
        )

    return f"{verdict}\n\n{table}"


async def test_connection(symbol: str) -> str:
    """Probe Revolut X with a read-only ticker + balances call. No orders are placed.

    Accepts either a bare symbol (``BTC-EUR``) or a Dataset value (``BTC-EUR|1h``).
    """
    if not symbol:
        raise gr.Error("Select a dataset to probe (e.g. BTC-EUR).")
    if "|" in symbol:
        symbol = symbol.split("|", 1)[0]

    runtime = get_runtime()
    if not has_revolutx_credentials(runtime.settings):
        raise gr.Error(
            "Revolut X credentials are not configured. Set REVOLUTX_API_KEY "
            "and REVOLUTX_PRIVATE_KEY (or REVOLUTX_PRIVATE_KEY_PATH) and "
            "rebuild the Space."
        )

    from cryptrink.exchange.revolutx import RevolutXExchange

    try:
        exchange = RevolutXExchange.from_settings(runtime.settings.revolutx)
    except ValueError as exc:
        raise gr.Error(f"Failed to load private key: {exc}") from exc

    try:
        try:
            await exchange.connect()
        except Exception as exc:
            raise gr.Error(f"Connect failed: {type(exc).__name__}: {exc}") from exc

        try:
            ticker = await exchange.get_ticker(symbol)
        except Exception as exc:
            raise gr.Error(f"get_ticker({symbol}) failed: {type(exc).__name__}: {exc}") from exc

        try:
            balances = await exchange.get_balances()
        except Exception as exc:
            balance_summary = f"_get_balances failed: {type(exc).__name__}: {exc}_"
        else:
            non_zero = {ccy: bal for ccy, bal in balances.items() if (bal.total or 0) > 0}
            if not non_zero:
                balance_summary = "_All balances are zero (no funds in account)._"
            else:
                lines = [
                    f"- **{ccy}**: total={bal.total} available={bal.available}"
                    for ccy, bal in sorted(non_zero.items())
                ]
                balance_summary = "\n".join(lines)
    finally:
        with contextlib.suppress(Exception):
            await exchange.close()

    rows: list[tuple[str, str]] = [
        ("Probed at", datetime.now(UTC).isoformat(timespec="seconds")),
        ("Symbol", ticker.symbol),
        ("Last", str(ticker.last)),
        ("Bid", str(ticker.bid)),
        ("Ask", str(ticker.ask)),
        ("24h volume", str(ticker.volume_24h)),
    ]
    table = "\n".join(f"| {label} | {value} |" for label, value in rows)
    return (
        "**Connection OK — no order was placed.**\n\n"
        "| Field | Value |\n| --- | --- |\n"
        f"{table}\n\n"
        "**Account balances**\n\n"
        f"{balance_summary}"
    )


# ----------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------

# Browser confirm that gates Start in live mode. Live mode is detected via the banner's
# semantic ``.ck-banner-live`` class (server-set), not a button label. Throwing cancels
# the Gradio event.
_START_CONFIRM_JS = (
    "() => { if (document.querySelector('.ck-banner-live')) {"
    " if (!confirm('Start LIVE loop? Real orders will be placed on Revolut X "
    "with account funds until you press Stop.')) throw new Error('cancelled'); } }"
)


def render() -> list[gr.Timer]:
    """Render the Live screen panel inside the workspace shell.

    Returns the screen-owned refresh timers so the shell can gate them active only
    while the Live screen is the visible screen.
    """
    runtime = get_runtime()
    strategy_options = strategy_registry.list_strategies()
    default_strategy = (
        runtime.settings.default_strategy
        if runtime.settings.default_strategy in strategy_options
        else (strategy_options[0] if strategy_options else None)
    )
    creds_present = has_revolutx_credentials(runtime.settings)
    discord_configured = runtime.settings.notifications.discord_enabled and bool(
        runtime.settings.notifications.discord_webhook_url.get_secret_value()
    )

    initial_choices = dataset_choices_sync()
    initial_value = initial_choices[0][1] if initial_choices else None

    with gr.Row(elem_classes=["ck-screen-cols"]):
        # ---- left: chart + activity ----
        with gr.Column(elem_classes=["ck-col-main"]):
            with gr.Group(elem_classes=["ck-card"]):
                gr.HTML('<div class="ck-card-title">Price (stored candles)</div>')
                chart_output = gr.Plot(elem_classes=["ck-plot"])
            activity_output = gr.HTML(_activity_html(None))

        # ---- right: config + status ----
        with gr.Column(scale=0, elem_classes=["ck-col-320"]):
            with gr.Group(elem_classes=["ck-card"]):
                gr.HTML('<div class="ck-section-label">Loop configuration</div>')
                strategy_input = gr.Dropdown(
                    choices=strategy_options, value=default_strategy, label="Strategy"
                )
                dataset_input = gr.Dropdown(
                    choices=initial_choices,
                    value=initial_value,
                    label="Dataset (symbol @ timeframe)",
                    allow_custom_value=True,
                )
                with gr.Row():
                    interval_input = gr.Number(value=60.0, label="Interval (s)", minimum=1)
                    balance_input = gr.Number(value=10000.0, label="Paper balance (€)")
                with gr.Accordion("Advanced · risk & notifications", open=False):
                    risk = runtime.settings.risk
                    gr.HTML(
                        '<div class="ck-kv-row"><span style="color:var(--faint)">'
                        "Max position size</span>"
                        f'<span class="ck-mono">{float(risk.max_position_size_pct) * 100:.0f}%'
                        "</span></div>"
                    )
                    heartbeat_enabled_input = gr.Checkbox(
                        value=False,
                        label="Discord heartbeat",
                        info=(
                            "Periodic 'I'm alive' embed to Discord."
                            if discord_configured
                            else "Configure NOTIFY_DISCORD_* in Space secrets first."
                        ),
                        interactive=discord_configured,
                    )
                    heartbeat_interval_input = gr.Number(
                        value=900.0,
                        label="Heartbeat interval (s)",
                        minimum=10,
                        interactive=discord_configured,
                    )
                    test_discord_btn = gr.Button(
                        "Test Discord",
                        elem_classes=["ck-btn-secondary"],
                        interactive=discord_configured,
                    )
                with gr.Row():
                    start_btn = gr.Button("Start", elem_classes=["ck-btn-primary"])
                    stop_btn = gr.Button("Stop", elem_classes=["ck-btn-stop"])
                if creds_present:
                    with gr.Row():
                        test_btn = gr.Button("Test connection", elem_classes=["ck-btn-secondary"])
                        preflight_btn = gr.Button("Pre-flight", elem_classes=["ck-btn-secondary"])

            _, initial_status = refresh_status()
            status_output = gr.HTML(initial_status)

    # diagnostics output (spans below the columns; only meaningful with creds/Discord)
    diag_output = gr.Markdown(visible=False)

    # ---- wiring ----
    dataset_input.change(fn=load_candle_chart, inputs=[dataset_input], outputs=[chart_output])
    dataset_input.focus(fn=refresh_datasets, inputs=[dataset_input], outputs=[dataset_input])

    # Auto-refresh while the Live screen is open: loop status/activity from the
    # in-memory snapshot (cheap, 3s) and the candlestick from stored OHLCV (DB read,
    # 6s — also fills the chart shortly after the screen is opened). Both no-op when
    # Live isn't the visible screen so they don't poll in the background.
    def _status_tick() -> tuple[object, object]:
        if get_active_screen() != "live":
            return gr.update(), gr.update()
        return refresh_status()

    status_timer = gr.Timer(3.0, active=False)
    status_timer.tick(fn=_status_tick, inputs=None, outputs=[activity_output, status_output])

    async def _chart_tick(dataset_value: str | None) -> object:
        if get_active_screen() != "live":
            return gr.update()
        return await load_candle_chart(dataset_value)

    chart_timer = gr.Timer(6.0, active=False)
    chart_timer.tick(fn=_chart_tick, inputs=[dataset_input], outputs=[chart_output])

    start_btn.click(
        fn=start_loop,
        inputs=[
            strategy_input,
            dataset_input,
            interval_input,
            balance_input,
            heartbeat_enabled_input,
            heartbeat_interval_input,
        ],
        outputs=[activity_output, status_output],
        js=_START_CONFIRM_JS,
    )
    stop_btn.click(fn=stop_loop, inputs=[], outputs=[activity_output, status_output])

    # Test Discord: fire a synthetic embed and report the webhook's actual response in the
    # diagnostics area. Non-interactive (so unclickable) unless Discord is configured.
    test_discord_btn.click(fn=test_discord, inputs=[], outputs=[diag_output])

    if creds_present:
        test_btn.click(fn=test_connection, inputs=[dataset_input], outputs=[diag_output]).then(
            fn=lambda: gr.update(visible=True), outputs=[diag_output]
        )
        preflight_btn.click(
            fn=preflight_order, inputs=[dataset_input, balance_input], outputs=[diag_output]
        ).then(fn=lambda: gr.update(visible=True), outputs=[diag_output])

    # Dashboard is folded into the Live screen as a stacked monitoring section (pass 4).
    # Its refresh timer is returned alongside Live's own so the shell gates all three
    # active only while Live is visible.
    dashboard_timers = dashboard.render_section()

    return [status_timer, chart_timer, *dashboard_timers]
