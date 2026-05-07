"""Data tab for the Cryptrink Gradio web app.

Backfills the OHLCV table from Revolut X's ``/candles/{symbol}`` endpoint,
the only authoritative historical-candles source the exchange exposes.
The Backtest, Suggest, and Live tabs all read from the OHLCV table, so
this is the entry point for "I want real backtests, not the synthetic
seed".

Two flows:
- **Backfill** — Symbol + timeframe + date range. Pages :meth:`backfill_candles`
  until the range is covered (the API caps each page at ~5000 candles).
- **Wipe** — Drops every OHLCV row for a given symbol + timeframe.
  Typed-confirm guard so it can't fire accidentally.

Both flows require Revolut X credentials. The tab's Markdown banner
mirrors the cred state so the operator doesn't see disabled controls
without an explanation.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime

import gradio as gr
import pandas as pd
from sqlalchemy import delete, func, select

from cryptrink.cli.utils import init_db_schema
from cryptrink.data.storage import OHLCV as OHLCVModel
from cryptrink.data.storage import OHLCVRepository
from cryptrink.web.live_setup import has_revolutx_credentials
from cryptrink.web.state import get_runtime

_SUPPORTED_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

# Module-level cache for the symbol list fetched from Revolut X.
# Populated by the "Refresh symbols" button so subsequent renders + clicks
# see the live vocabulary instead of the configured defaults. Other tabs
# can read this in a follow-up to share the same dropdown options.
_cached_symbols: list[str] = []


def _parse_date(value: str, *, end_of_day: bool = False) -> datetime:
    """Parse a YYYY-MM-DD string into a timezone-aware UTC datetime.

    Set ``end_of_day=True`` for end-date inputs so the operator's
    inclusive-feeling "until 2024-02-01" actually covers the whole day.
    """
    parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    if end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999000)
    return parsed


async def _stored_count(symbol: str, timeframe: str) -> int:
    """Count OHLCV rows currently persisted for ``(symbol, timeframe)``."""
    runtime = get_runtime()
    session_factory = runtime.session_factory
    async with session_factory() as session:
        stmt = (
            select(func.count())
            .select_from(OHLCVModel)
            .where(OHLCVModel.symbol == symbol, OHLCVModel.timeframe == timeframe)
        )
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)


async def backfill(
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> str:
    """Fetch a date range from /candles and persist via :class:`OHLCVRepository`.

    Reports counts (fetched, persisted, total stored) in markdown.
    """
    if not symbol:
        raise gr.Error("Enter a symbol (e.g. BTC-EUR).")
    if not start_date:
        raise gr.Error("Enter a start date (YYYY-MM-DD).")

    runtime = get_runtime()
    if not has_revolutx_credentials(runtime.settings):
        raise gr.Error(
            "Revolut X credentials are not configured. /candles is a signed "
            "endpoint — set REVOLUTX_API_KEY and REVOLUTX_PRIVATE_KEY (or "
            "REVOLUTX_PRIVATE_KEY_PATH) before running a backfill."
        )

    try:
        start_dt = _parse_date(start_date)
        end_dt = _parse_date(end_date, end_of_day=True) if end_date else datetime.now(UTC)
    except ValueError as exc:
        raise gr.Error(f"Invalid date: {exc}") from exc

    if end_dt <= start_dt:
        raise gr.Error("End date must be after start date.")

    await init_db_schema(runtime.session_factory)

    from cryptrink.exchange.revolutx import RevolutXExchange, timeframe_to_interval_minutes

    try:
        timeframe_to_interval_minutes(timeframe)
    except ValueError as exc:
        raise gr.Error(str(exc)) from exc

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

    since_ms = int(start_dt.timestamp() * 1000)
    until_ms = int(end_dt.timestamp() * 1000)

    try:
        await exchange.connect()
        try:
            candles = await exchange.backfill_candles(
                symbol=symbol,
                timeframe=timeframe,
                since_ms=since_ms,
                until_ms=until_ms,
            )
        except Exception as exc:
            raise gr.Error(
                f"backfill_candles({symbol}, {timeframe}) failed: {type(exc).__name__}: {exc}"
            ) from exc
    finally:
        with contextlib.suppress(Exception):
            await exchange.close()

    repository = OHLCVRepository(runtime.session_factory)
    saved = await repository.save_batch(candles) if candles else 0
    total = await _stored_count(symbol, timeframe)

    earliest_iso = (
        datetime.fromtimestamp(candles[0]["timestamp"] / 1000, tz=UTC).isoformat(timespec="seconds")
        if candles
        else "—"
    )
    latest_iso = (
        datetime.fromtimestamp(candles[-1]["timestamp"] / 1000, tz=UTC).isoformat(
            timespec="seconds"
        )
        if candles
        else "—"
    )

    return (
        f"**Backfill complete.**\n\n"
        f"| Field | Value |\n"
        f"| --- | --- |\n"
        f"| Symbol | `{symbol}` |\n"
        f"| Timeframe | `{timeframe}` |\n"
        f"| Requested range | {start_dt.date()} → {end_dt.date()} |\n"
        f"| Candles fetched | {len(candles)} |\n"
        f"| Earliest fetched | {earliest_iso} |\n"
        f"| Latest fetched | {latest_iso} |\n"
        f"| Persisted this run | {saved} |\n"
        f"| Total stored ({symbol} {timeframe}) | {total} |\n"
    )


async def wipe(symbol: str, timeframe: str, confirm: str) -> str:
    """Delete every OHLCV row for ``(symbol, timeframe)``.

    Requires the operator to type ``DELETE`` into the confirm box. The
    primary safeguard is the typed-confirm — there is no Are-you-sure
    modal in plain Gradio.
    """
    if not symbol:
        raise gr.Error("Enter a symbol.")
    if confirm.strip() != "DELETE":
        raise gr.Error("Type DELETE in the confirm box to wipe the rows.")

    runtime = get_runtime()
    await init_db_schema(runtime.session_factory)

    # Count first so the result message is informative; SQLAlchemy's
    # CursorResult.rowcount is mistyped as Result[Any].rowcount in the
    # current stubs, and inferring it correctly would require a noisy
    # cast. A separate count query is honest.
    async with runtime.session_factory() as session:
        count_stmt = (
            select(func.count())
            .select_from(OHLCVModel)
            .where(OHLCVModel.symbol == symbol, OHLCVModel.timeframe == timeframe)
        )
        deleted = int((await session.execute(count_stmt)).scalar_one() or 0)

        delete_stmt = delete(OHLCVModel).where(
            OHLCVModel.symbol == symbol, OHLCVModel.timeframe == timeframe
        )
        await session.execute(delete_stmt)
        await session.commit()

    return f"**Wipe complete.**\n\nDeleted {deleted} OHLCV rows for `{symbol}` `{timeframe}`."


async def refresh_counts(symbol: str, timeframe: str) -> str:
    """Show how many candles are currently persisted for ``(symbol, timeframe)``."""
    if not symbol:
        return "_Enter a symbol to inspect._"
    runtime = get_runtime()
    await init_db_schema(runtime.session_factory)
    total = await _stored_count(symbol, timeframe)
    return f"**{total}** candles currently stored for `{symbol}` `{timeframe}`."


async def database_overview() -> pd.DataFrame:
    """Return a one-row-per-(symbol, timeframe) summary of stored OHLCV.

    Single SQL ``GROUP BY`` so the cost is constant regardless of how many
    candles are stored. Empty database returns an empty frame with the
    expected columns so the dataframe component renders without errors.
    """
    runtime = get_runtime()
    await init_db_schema(runtime.session_factory)

    columns = ["Symbol", "Timeframe", "Candles", "Earliest (UTC)", "Latest (UTC)"]
    async with runtime.session_factory() as session:
        # ``count`` collides with tuple.count on SQLAlchemy Row, so the
        # label is ``candle_count`` to keep static type-checking happy.
        stmt = (
            select(
                OHLCVModel.symbol,
                OHLCVModel.timeframe,
                func.count().label("candle_count"),
                func.min(OHLCVModel.timestamp).label("earliest"),
                func.max(OHLCVModel.timestamp).label("latest"),
            )
            .group_by(OHLCVModel.symbol, OHLCVModel.timeframe)
            .order_by(OHLCVModel.symbol, OHLCVModel.timeframe)
        )
        result = await session.execute(stmt)
        rows = list(result.all())

    if not rows:
        return pd.DataFrame(columns=columns)

    data: list[dict[str, object]] = []
    for row in rows:
        earliest = datetime.fromtimestamp(int(row.earliest) / 1000, tz=UTC)
        latest = datetime.fromtimestamp(int(row.latest) / 1000, tz=UTC)
        data.append(
            {
                "Symbol": row.symbol,
                "Timeframe": row.timeframe,
                "Candles": int(row.candle_count),
                "Earliest (UTC)": earliest.isoformat(timespec="seconds"),
                "Latest (UTC)": latest.isoformat(timespec="seconds"),
            }
        )
    return pd.DataFrame(data, columns=columns)


async def refresh_symbols(current: str) -> tuple[object, str]:
    """Pull the live symbol list from Revolut X and update the dropdown.

    Returns a tuple of (Gradio update for the symbol Dropdown, status
    markdown). Failures (no creds, signing/network errors) surface as
    :class:`gr.Error` so the dropdown is left untouched and the operator
    sees the underlying message in a banner.
    """
    global _cached_symbols
    runtime = get_runtime()
    if not has_revolutx_credentials(runtime.settings):
        raise gr.Error(
            "Revolut X credentials are not configured. Set REVOLUTX_API_KEY "
            "and REVOLUTX_PRIVATE_KEY (or REVOLUTX_PRIVATE_KEY_PATH) before "
            "refreshing the symbol list."
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
        await exchange.connect()
        try:
            symbols = sorted(await exchange.get_symbols())
        except Exception as exc:
            raise gr.Error(f"get_symbols() failed: {type(exc).__name__}: {exc}") from exc
    finally:
        with contextlib.suppress(Exception):
            await exchange.close()

    if not symbols:
        raise gr.Error("Revolut X returned an empty symbol list.")

    _cached_symbols = symbols
    new_value = current if current in symbols else symbols[0]
    return (
        gr.update(choices=symbols, value=new_value),
        f"_Loaded {len(symbols)} symbols from Revolut X._",
    )


def _initial_symbol_choices(default_symbol: str) -> list[str]:
    """Choose the initial dropdown choices: cached if available, else defaults."""
    if _cached_symbols:
        return _cached_symbols
    runtime = get_runtime()
    fallback = list(runtime.settings.symbols) if runtime.settings.symbols else [default_symbol]
    if default_symbol not in fallback:
        fallback.insert(0, default_symbol)
    return fallback


def render() -> None:
    """Render the Data tab UI inside an enclosing :class:`gr.Tabs`."""
    runtime = get_runtime()
    default_symbol = runtime.settings.symbols[0] if runtime.settings.symbols else "BTC-EUR"
    creds_present = has_revolutx_credentials(runtime.settings)
    cred_hint = (
        "_Revolut X credentials detected — backfills will hit the live "
        "`/candles/{symbol}` endpoint._"
        if creds_present
        else "_Revolut X credentials are missing; the Backfill button will "
        "report an error until you configure them._"
    )

    with gr.Tab("Data"):
        gr.Markdown(
            "Manage the historical OHLCV table the Backtest, Suggest, and "
            "Live tabs read from. **Backfill** pages "
            "`/candles/{symbol}` until the requested range is covered; "
            "**Wipe** drops every row for a given symbol + timeframe.\n\n" + cred_hint
        )
        with gr.Row():
            symbol_input = gr.Dropdown(
                choices=_initial_symbol_choices(default_symbol),
                value=default_symbol,
                label="Symbol",
                allow_custom_value=True,
            )
            timeframe_input = gr.Dropdown(
                choices=_SUPPORTED_TIMEFRAMES,
                value="1h",
                label="Timeframe",
            )
        with gr.Row():
            refresh_symbols_btn = gr.Button("Refresh symbols from Revolut X", variant="secondary")
            symbols_status = gr.Markdown()
        refresh_symbols_btn.click(
            fn=refresh_symbols,
            inputs=[symbol_input],
            outputs=[symbol_input, symbols_status],
        )

        gr.Markdown("### Backfill from `/candles/{symbol}`")
        with gr.Row():
            start_input = gr.Textbox(value="2024-01-01", label="Start (YYYY-MM-DD)")
            end_input = gr.Textbox(value="", label="End (YYYY-MM-DD, blank = now)")
        backfill_btn = gr.Button("Backfill", variant="primary")
        backfill_output = gr.Markdown()
        backfill_btn.click(
            fn=backfill,
            inputs=[symbol_input, timeframe_input, start_input, end_input],
            outputs=[backfill_output],
        )

        gr.Markdown(
            "### Database overview\n"
            "One row per `(symbol, timeframe)` currently in the OHLCV "
            "table — useful to confirm a backfill landed and to spot gaps."
        )
        overview_btn = gr.Button("Refresh database overview")
        overview_output = gr.Dataframe(
            value=pd.DataFrame(
                columns=["Symbol", "Timeframe", "Candles", "Earliest (UTC)", "Latest (UTC)"]
            ),
            label="Stored OHLCV",
            interactive=False,
        )
        overview_btn.click(fn=database_overview, inputs=[], outputs=[overview_output])

        gr.Markdown(
            "### Inspect a single pair\n"
            "Quick count of candles for the symbol + timeframe selected above."
        )
        refresh_btn = gr.Button("Count candles for selected pair")
        counts_output = gr.Markdown()
        refresh_btn.click(
            fn=refresh_counts,
            inputs=[symbol_input, timeframe_input],
            outputs=[counts_output],
        )

        gr.Markdown(
            "### Wipe (destructive)\n"
            "Drops every OHLCV row for the chosen `(symbol, timeframe)` "
            "above. Type `DELETE` to confirm."
        )
        with gr.Row():
            confirm_input = gr.Textbox(value="", label="Type DELETE to confirm")
            wipe_btn = gr.Button("Wipe", variant="stop")
        wipe_output = gr.Markdown()
        wipe_btn.click(
            fn=wipe,
            inputs=[symbol_input, timeframe_input, confirm_input],
            outputs=[wipe_output],
        )
