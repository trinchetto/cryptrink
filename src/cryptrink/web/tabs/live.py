"""Live tab for the Cryptrink Gradio web app.

Drives a strategy on a periodic interval via :class:`LiveLoop`. Mode is
selectable: paper (default) uses :class:`PaperExecutor` against the
historical OHLCV in the configured database; live builds a
:class:`LiveExecutor` against :class:`RevolutXExchange` when
``REVOLUTX_API_KEY`` plus a private key are present, and silently falls
back to paper otherwise so the Start button never accidentally turns
into real-money trading.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import gradio as gr

from cryptrink.cli.utils import init_db_schema
from cryptrink.runtime import resolve_strategy
from cryptrink.strategies import registry as strategy_registry
from cryptrink.strategies.base import SignalType
from cryptrink.web.live_loop import LiveLoop, LiveLoopState, get_active_loop, set_active_loop
from cryptrink.web.live_setup import LiveMode, build_live_components, has_revolutx_credentials
from cryptrink.web.state import (
    Dataset,
    default_symbol,
    get_runtime,
    get_symbol_choices,
    list_datasets,
    list_datasets_sync,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from cryptrink.execution.base import ExecutionResult
    from cryptrink.execution.repository import OrderRepository
    from cryptrink.notifications.discord import DiscordNotifier
    from cryptrink.strategies.base import Signal


def _build_discord_callback(
    notifier: DiscordNotifier,
    order_repo: OrderRepository,
) -> Callable[[Signal, ExecutionResult], Awaitable[None]]:
    """Wrap the discord notifier in an on_signal-shaped callback.

    Only successful executions that produced an ``order_id`` actually fire
    a Discord embed. HOLD signals and rejected executions are skipped
    silently — they're already visible in the loop's status pane.
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


async def start_loop(
    strategy_name: str,
    dataset_value: str | None,
    interval_seconds: float,
    initial_balance: float,
    mode_value: str,
) -> str:
    """Build a fresh :class:`LiveLoop` and start it. Used by the Start button."""
    if not strategy_name:
        raise gr.Error("Select a strategy.")
    if not dataset_value:
        raise gr.Error(
            "Select a dataset. Open the Data tab and run Backfill if the "
            "dropdown is empty, then click Refresh datasets here."
        )
    try:
        symbol, dataset_timeframe = Dataset.parse(dataset_value)
    except ValueError as exc:
        raise gr.Error(f"Malformed dataset value: {exc}") from exc
    if interval_seconds <= 0:
        raise gr.Error("Interval must be positive.")

    try:
        requested_mode = LiveMode(mode_value)
    except ValueError as exc:
        raise gr.Error(f"Unknown mode '{mode_value}'.") from exc

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
            f"but the selected dataset is {dataset_timeframe!r}. The Live loop "
            f"would fetch candles at {strategy.timeframe!r} and bypass the "
            f"selected dataset entirely. Pick a dataset that matches the "
            f"strategy's timeframe, or backfill {strategy.timeframe!r} for "
            f"{symbol} from the Data tab."
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
    if components.notifier is not None:
        from cryptrink.execution.repository import OrderRepository

        on_signal = _build_discord_callback(
            notifier=components.notifier,
            order_repo=OrderRepository(session_factory),
        )

    loop = LiveLoop(
        engine=components.engine,
        strategy=strategy,
        symbol=symbol,
        data_feed=components.data_feed,
        interval_seconds=float(interval_seconds),
        on_signal=on_signal,
        on_stop=components.cleanup,
    )
    set_active_loop(loop)
    await loop.start()

    return _render_status(
        loop.snapshot(),
        engine_id=components.engine.engine_id,
        mode=components.mode,
        requested_mode=requested_mode,
    )


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


def _render_status(
    state: LiveLoopState | None,
    *,
    engine_id: str | None = None,
    mode: LiveMode | None = None,
    requested_mode: LiveMode | None = None,
) -> str:
    """Format a :class:`LiveLoopState` into a markdown status block."""
    if state is None:
        return "_No live loop has been started._"

    rows: list[tuple[str, str]] = [
        ("Status", "🟢 Running" if state.running else "⏹ Stopped"),
        ("Symbol", state.symbol or "—"),
        ("Strategy", state.strategy_name or "—"),
        ("Interval", f"{state.interval_seconds:.0f}s"),
    ]
    if mode is not None:
        if requested_mode is not None and requested_mode != mode:
            rows.append(
                (
                    "Mode",
                    f"**{mode.value}** "
                    f"(requested {requested_mode.value} — credentials missing, "
                    "fell back to paper)",
                )
            )
        else:
            rows.append(("Mode", mode.value))
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


async def test_discord(_: object = None) -> str:
    """Send a synthetic notification to the configured Discord webhook.

    Surfaced as the "Test Discord notification" button so the operator
    can verify the webhook is wired up before going live. The trade
    path swallows webhook errors silently (intentionally — a noisy
    webhook shouldn't break trading), so this dedicated probe is the
    only place the operator gets to see the actual HTTP response.
    """
    runtime = get_runtime()
    notifications = runtime.settings.notifications
    if not notifications.discord_enabled:
        return (
            "**Discord disabled.** Set `NOTIFY_DISCORD_ENABLED=true` and "
            "`NOTIFY_DISCORD_WEBHOOK_URL=<webhook>` in the Space secrets, then "
            "restart the Space."
        )
    webhook = notifications.discord_webhook_url.get_secret_value()
    if not webhook:
        return (
            "**Webhook URL is empty.** `NOTIFY_DISCORD_ENABLED` is true but "
            "`NOTIFY_DISCORD_WEBHOOK_URL` is unset — set it in the Space secrets."
        )

    from cryptrink.notifications.discord import DiscordNotifier

    notifier = DiscordNotifier(webhook_url=webhook, enabled=True)
    result = await notifier.send_test()
    if result.ok:
        return (
            f"✅ **Webhook OK** ({result.status}). Check your Discord channel — "
            "you should see a 'Cryptrink test notification' embed. If you don't, "
            "the webhook is delivering to a different channel than you expect."
        )
    return (
        f"❌ **Webhook failed** (HTTP {result.status}).\n\n"
        f"```\n{result.detail}\n```\n\n"
        "Common causes:\n"
        "- 401/403: webhook was revoked or you pasted a Slack-shaped URL.\n"
        "- 404: the webhook was deleted on the Discord side.\n"
        "- Network error: HF Space cannot reach `discord.com` (rare).\n"
        "Re-issue the webhook from Discord → Server Settings → Integrations "
        "and update the Space secret."
    )


async def preflight_order(dataset_value: str | None, initial_balance: float) -> str:
    """Look up Revolut X pair limits and check the planned order would clear them.

    The Live loop's first BUY allocates ``balance * max_position_size_pct``
    of the quote currency. Revolut X enforces ``min_order_size`` (in the
    base) and ``min_order_size_quote`` (in the quote) per pair --
    ``allocation = 1 EUR`` against a high-priced pair is dust the exchange
    rejects with an unhelpful generic error. This pre-flight surfaces
    the rejection in cryptrink with the exact constraint that fails, so
    the operator knows which knob to turn.
    """
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

    revolutx = runtime.settings.revolutx
    try:
        private_key_b64 = revolutx.get_private_key()
    except ValueError as exc:
        return f"❌ **Failed to load private key:** {exc}"

    exchange = RevolutXExchange(
        api_key=revolutx.api_key.get_secret_value(),
        private_key_base64=private_key_b64,
        base_url=revolutx.base_url,
    )

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

    # Compute the allocation the live loop would request on its first BUY.
    risk = runtime.settings.risk
    max_pct = Decimal(str(risk.max_position_size_pct))
    balance = Decimal(str(initial_balance))
    notional = balance * max_pct  # in the quote currency
    if current_price <= 0:
        return f"❌ **Invalid current price** ({current_price}) for {symbol}."
    quantity = notional / current_price

    rows = [
        ("Symbol", info.symbol),
        ("Status", info.status),
        ("Current price", f"{current_price} {info.quote}"),
        ("Configured balance", f"{balance} {info.quote}"),
        ("max_position_size_pct", f"{max_pct * 100}%"),
        ("Planned allocation", f"≈ {notional} {info.quote}"),
        ("Planned quantity", f"≈ {quantity} {info.base}"),
        ("min_order_size", f"{info.min_order_size} {info.base}"),
        ("min_order_size_quote", f"{info.min_order_size_quote} {info.quote}"),
        ("max_order_size", f"{info.max_order_size} {info.base}"),
        ("base_step", f"{info.base_step} {info.base}"),
    ]
    body = "\n".join(f"| {label} | {value} |" for label, value in rows)
    table = "| Field | Value |\n| --- | --- |\n" + body

    reason = info.reject_reason(quantity=quantity, notional=notional)
    if reason is None:
        verdict = (
            f"✅ **Order would clear all minimums** for `{symbol}`. The first "
            f"BUY the live loop emits will request ~{quantity} {info.base} "
            f"(~{notional} {info.quote})."
        )
    else:
        verdict = (
            f"❌ **Order would be rejected:** {reason}.\n\n"
            "Fixes:\n"
            f"- Raise `RISK_MAX_POSITION_SIZE_PCT` so the allocation clears the minimum.\n"
            f"- Pick a lower-priced pair (e.g. an asset already in your wallet).\n"
            f"- Top up the {info.quote} balance so a smaller percentage still clears."
        )

    return f"{verdict}\n\n{table}"


async def test_connection(symbol: str) -> str:
    """Probe Revolut X with a read-only ticker + balances call.

    Wired to the Test connection button. Builds a one-shot
    :class:`RevolutXExchange`, connects, fetches the ticker for the
    operator-supplied symbol and the account balances, then closes the
    connection. **No orders are placed.**

    Catches both signing/connection errors and per-call API errors so
    each failure surfaces in the UI as a friendly :class:`gr.Error` with
    the underlying message instead of a server-side traceback.
    """
    if not symbol:
        raise gr.Error("Enter a symbol to probe (e.g. BTC-EUR).")

    runtime = get_runtime()
    if not has_revolutx_credentials(runtime.settings):
        raise gr.Error(
            "Revolut X credentials are not configured. Set REVOLUTX_API_KEY "
            "and REVOLUTX_PRIVATE_KEY (or REVOLUTX_PRIVATE_KEY_PATH) and "
            "rebuild the Space."
        )

    from cryptrink.exchange.revolutx import RevolutXExchange

    revolutx = runtime.settings.revolutx
    try:
        private_key_b64 = revolutx.get_private_key()
    except ValueError as exc:
        raise gr.Error(f"Failed to load private key: {exc}") from exc

    exchange = RevolutXExchange(
        api_key=revolutx.api_key.get_secret_value(),
        private_key_base64=private_key_b64,
        base_url=revolutx.base_url,
    )

    try:
        try:
            await exchange.connect()
        except Exception as exc:
            raise gr.Error(f"Connect failed: {type(exc).__name__}: {exc}") from exc

        try:
            ticker = await exchange.get_ticker(symbol)
        except Exception as exc:
            raise gr.Error(f"get_ticker({symbol}) failed: {type(exc).__name__}: {exc}") from exc

        balance_summary: str
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


def render() -> None:
    """Render the Live tab UI inside an enclosing :class:`gr.Tabs`."""
    runtime = get_runtime()
    strategy_options = strategy_registry.list_strategies()
    default_strategy = (
        runtime.settings.default_strategy
        if runtime.settings.default_strategy in strategy_options
        else (strategy_options[0] if strategy_options else None)
    )
    creds_present = has_revolutx_credentials(runtime.settings)
    default_mode = LiveMode.PAPER.value
    if creds_present:
        mode_choices = [LiveMode.PAPER.value, LiveMode.LIVE.value]
        mode_info = "Live mode places real orders on Revolut X."
        cred_hint = "_Revolut X credentials detected — Live mode will place real orders._"
    else:
        # Hide Live entirely when creds are missing. Gradio's Radio doesn't
        # support per-choice disabling, so omitting is the cleanest way to
        # convey "not available right now". The info hint explains why.
        mode_choices = [LiveMode.PAPER.value]
        mode_info = (
            "Set REVOLUTX_API_KEY and REVOLUTX_PRIVATE_KEY (or "
            "REVOLUTX_PRIVATE_KEY_PATH) in the environment to unlock Live mode."
        )
        cred_hint = "_No Revolut X credentials in env; Live mode is hidden until they are set._"

    with gr.Tab("Live"):
        gr.Markdown(
            "Run a strategy on a periodic interval. Each tick fetches the latest "
            "candle, generates a signal, and routes it through risk validation and "
            "the configured executor. **Paper** mode replays signals against the "
            "stored OHLCV in the configured database; **Live** mode places real "
            "orders on Revolut X (requires REVOLUTX_API_KEY + REVOLUTX_PRIVATE_KEY "
            "in the environment).\n\nThe Dataset dropdown lists what's actually "
            "in the OHLCV table — the strategy's preferred timeframe must match "
            "the selected dataset so the loop fetches the right candles.\n\n" + cred_hint
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
            refresh_datasets_btn = gr.Button("Refresh datasets", variant="secondary")
        with gr.Row():
            interval_input = gr.Number(value=60.0, label="Interval (seconds)", minimum=1)
            balance_input = gr.Number(value=10000.0, label="Initial paper balance (EUR)")
            mode_input = gr.Radio(
                choices=mode_choices,
                value=default_mode,
                label="Mode",
                info=mode_info,
            )

        with gr.Row():
            start_btn = gr.Button("Start", variant="primary")
            stop_btn = gr.Button("Stop", variant="stop")
            refresh_btn = gr.Button("Refresh status")

        status_output = gr.Markdown(value=refresh_status())

        refresh_datasets_btn.click(
            fn=refresh_datasets, inputs=[dataset_input], outputs=[dataset_input]
        )
        dataset_input.focus(fn=refresh_datasets, inputs=[dataset_input], outputs=[dataset_input])
        start_btn.click(
            fn=start_loop,
            inputs=[strategy_input, dataset_input, interval_input, balance_input, mode_input],
            outputs=[status_output],
        )
        stop_btn.click(fn=stop_loop, inputs=[], outputs=[status_output])
        refresh_btn.click(fn=refresh_status, inputs=[], outputs=[status_output])

        if creds_present:
            gr.Markdown(
                "---\n\n"
                "### Test live connection\n"
                "Probe Revolut X with a read-only ticker + account-balance "
                "call. **No orders are placed.** Run this once after adding "
                "credentials to confirm signing and authentication work."
            )
            with gr.Row():
                test_symbol_input = gr.Dropdown(
                    choices=get_symbol_choices(),
                    value=default_symbol(),
                    label="Probe symbol",
                    allow_custom_value=True,
                    scale=2,
                )
                test_btn = gr.Button("Test live connection", variant="secondary")
            test_output = gr.Markdown()
            test_btn.click(
                fn=test_connection,
                inputs=[test_symbol_input],
                outputs=[test_output],
            )

            gr.Markdown(
                "---\n\n"
                "### Pre-flight order check\n"
                "Look up the selected pair's `min_order_size` / "
                "`min_order_size_quote` from Revolut X's `/configuration/pairs`, "
                "then compare against the order the live loop would place "
                "(balance * `RISK_MAX_POSITION_SIZE_PCT` / current price). "
                "Surfaces 'this order would be rejected as dust' before you hit Start."
            )
            preflight_btn = gr.Button("Run pre-flight check", variant="secondary")
            preflight_output = gr.Markdown()
            preflight_btn.click(
                fn=preflight_order,
                inputs=[dataset_input, balance_input],
                outputs=[preflight_output],
            )

        gr.Markdown(
            "---\n\n"
            "### Test Discord notification\n"
            "Send a synthetic embed to the configured webhook so you can "
            "verify trade alerts will land on your phone before you go live. "
            "Surfaces the exact HTTP status if the webhook is misconfigured "
            "(401/403 from a revoked webhook, 404 from a deleted webhook, etc.)."
        )
        discord_btn = gr.Button("Test Discord notification", variant="secondary")
        discord_output = gr.Markdown()
        discord_btn.click(fn=test_discord, inputs=[], outputs=[discord_output])
