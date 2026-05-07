"""Data tab for the Cryptrink Gradio web app.

Backfills the OHLCV table from Revolut X's ``/candles/{symbol}`` endpoint,
the only authoritative historical-candles source the exchange exposes.
The Backtest, Suggest, and Live tabs all read from the OHLCV table, so
this is the entry point for "I want real backtests, not the synthetic
seed".

Three flows:
- **Backfill** — Symbol + timeframe + date range. Streams progress as
  it pages :meth:`iter_candle_pages` (Revolut X's ``/candles`` endpoint
  rejects single requests that would return more than ~50,000 rows, so
  pagination is mandatory for wide ranges).
- **Database overview** — one row per ``(symbol, timeframe)`` plus the
  total file size on disk so operators can spot a bloating DB.
- **Wipe** — Drops every OHLCV row for a given symbol + timeframe.
  Typed-confirm guard so it can't fire accidentally.

The Symbol input is a Dropdown sourced from
:func:`cryptrink.web.state.get_symbol_choices`, populated by the
"Refresh symbols from Revolut X" button via ``/configuration/pairs``.
Other tabs read the same cache so a refresh + page reload propagates
the live vocabulary.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import gradio as gr
import pandas as pd
from sqlalchemy import delete, func, select

from cryptrink.cli.utils import init_db_schema
from cryptrink.data.storage import OHLCV as OHLCVModel
from cryptrink.data.storage import OHLCVRepository
from cryptrink.web.live_setup import has_revolutx_credentials
from cryptrink.web.state import (
    default_symbol,
    get_runtime,
    get_symbol_choices,
    set_cached_symbols,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_SUPPORTED_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]


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


def _sqlite_file_path(db_url: str) -> Path | None:
    """Return the on-disk path for a sqlite+aiosqlite URL, or None.

    Handles both ``sqlite+aiosqlite:///relative.db`` (3 slashes) and
    ``sqlite+aiosqlite:////absolute/path.db`` (4 slashes — the form HF
    Spaces uses for ``/data/cryptrink.db``).
    """
    prefix = "sqlite+aiosqlite:///"
    if not db_url.startswith(prefix):
        return None
    raw = db_url[len(prefix) :]
    if raw == ":memory:":
        return None
    # Three-slash form leaves ``raw`` as a relative path; four-slash
    # form leaves it with a leading slash, i.e. an absolute path.
    return Path(raw)


def _format_db_size(db_url: str) -> str:
    """Render the sqlite file size as markdown for the overview header."""
    path = _sqlite_file_path(db_url)
    if path is None:
        if db_url.endswith(":memory:"):
            return "_Database is in-memory; no file size._"
        return f"_DB URL `{db_url}` is not a sqlite file; size unavailable._"
    if not path.exists():
        return f"_Database file `{path}` does not exist yet._"
    size_bytes = path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    return f"**Database size:** {size_mb:.2f} MB (`{path}`)"


def _now_iso() -> str:
    """Compact UTC timestamp for streaming log lines."""
    return datetime.now(UTC).strftime("%H:%M:%S")


def _render_log(lines: list[str]) -> str:
    """Render a streaming log as a markdown code-block.

    Caps the output at the most-recent 100 lines so a long backfill
    doesn't grow an unbounded markdown body.
    """
    tail = lines[-100:]
    return "```\n" + "\n".join(tail) + "\n```"


async def backfill(
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> AsyncIterator[str]:
    """Stream backfill progress to the Data tab.

    Async generator: each ``yield`` replaces the bound markdown output
    with the latest log + (eventually) summary. Pagination is done
    inline (rather than via :meth:`backfill_candles`) so the operator
    sees per-page progress while pages stream in.
    """
    log: list[str] = []

    def emit(message: str) -> str:
        log.append(f"[{_now_iso()}] {message}")
        return _render_log(log)

    yield emit("Validating inputs…")

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

    yield emit(f"Range: {start_dt.isoformat()} → {end_dt.isoformat()} ({timeframe})")

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

    yield emit("Connecting to Revolut X…")
    try:
        await exchange.connect()
    except Exception as exc:
        raise gr.Error(f"Connect failed: {type(exc).__name__}: {exc}") from exc
    yield emit("Connected. Paging /candles backwards from `until`.")

    seen: set[int] = set()
    collected: list[dict[str, Any]] = []
    page_num = 0

    try:
        try:
            async for page in exchange.iter_candle_pages(
                symbol=symbol,
                timeframe=timeframe,
                since_ms=since_ms,
                until_ms=until_ms,
            ):
                page_num += 1
                new = 0
                for candle in page:
                    ts = int(candle["timestamp"])
                    if ts in seen:
                        continue
                    seen.add(ts)
                    collected.append(candle)
                    new += 1
                earliest = datetime.fromtimestamp(int(page[0]["timestamp"]) / 1000, tz=UTC)
                latest = datetime.fromtimestamp(int(page[-1]["timestamp"]) / 1000, tz=UTC)
                yield emit(
                    f"Page {page_num}: {len(page):>4} candles "
                    f"({new} new) • {earliest.isoformat(timespec='seconds')} → "
                    f"{latest.isoformat(timespec='seconds')}"
                )
        except Exception as exc:
            raise gr.Error(f"Page {page_num + 1} failed: {type(exc).__name__}: {exc}") from exc
    finally:
        with contextlib.suppress(Exception):
            await exchange.close()
            yield emit("Connection closed.")

    # Filter to the requested window and sort.
    candles = sorted(
        (c for c in collected if since_ms <= int(c["timestamp"]) <= until_ms),
        key=lambda c: int(c["timestamp"]),
    )

    yield emit(f"Persisting {len(candles)} candles to the OHLCV table…")
    repository = OHLCVRepository(runtime.session_factory)
    saved = await repository.save_batch(candles) if candles else 0
    total = await _stored_count(symbol, timeframe)
    yield emit(f"Persisted. Total stored for {symbol} {timeframe}: {total}.")

    earliest_iso = (
        datetime.fromtimestamp(int(candles[0]["timestamp"]) / 1000, tz=UTC).isoformat(
            timespec="seconds"
        )
        if candles
        else "—"
    )
    latest_iso = (
        datetime.fromtimestamp(int(candles[-1]["timestamp"]) / 1000, tz=UTC).isoformat(
            timespec="seconds"
        )
        if candles
        else "—"
    )

    summary = (
        "**Backfill complete.**\n\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        f"| Symbol | `{symbol}` |\n"
        f"| Timeframe | `{timeframe}` |\n"
        f"| Requested range | {start_dt.date()} → {end_dt.date()} |\n"
        f"| Pages fetched | {page_num} |\n"
        f"| Candles fetched | {len(candles)} |\n"
        f"| Earliest fetched | {earliest_iso} |\n"
        f"| Latest fetched | {latest_iso} |\n"
        f"| Persisted this run | {saved} |\n"
        f"| Total stored ({symbol} {timeframe}) | {total} |\n"
    )

    yield summary + "\n\n" + _render_log(log)


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


async def database_overview() -> tuple[str, pd.DataFrame]:
    """Return (size markdown, per-pair summary dataframe) for the overview section."""
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
        df = pd.DataFrame(columns=columns)
    else:
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
        df = pd.DataFrame(data, columns=columns)

    return _format_db_size(runtime.settings.database.url), df


async def refresh_symbols(current: str) -> tuple[object, str]:
    """Pull the live symbol list from Revolut X and update the dropdown.

    Updates :func:`cryptrink.web.state.set_cached_symbols` so other tabs'
    dropdowns pick up the live vocabulary on the next page reload.
    """
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

    set_cached_symbols(symbols)
    new_value = current if current in symbols else symbols[0]
    return (
        gr.update(choices=symbols, value=new_value),
        f"_Loaded {len(symbols)} symbols from Revolut X. "
        "Reload the page to update the dropdowns on the other tabs._",
    )


def render() -> None:
    """Render the Data tab UI inside an enclosing :class:`gr.Tabs`."""
    runtime = get_runtime()
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
                choices=get_symbol_choices(),
                value=default_symbol(),
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
        backfill_log = gr.Markdown()
        backfill_btn.click(
            fn=backfill,
            inputs=[symbol_input, timeframe_input, start_input, end_input],
            outputs=[backfill_log],
        )

        gr.Markdown(
            "### Database overview\n"
            "One row per `(symbol, timeframe)` currently in the OHLCV "
            "table — useful to confirm a backfill landed and to spot gaps. "
            "Total file size on disk is shown above the table so you can "
            "watch it grow."
        )
        overview_btn = gr.Button("Refresh database overview")
        db_size_output = gr.Markdown()
        overview_output = gr.Dataframe(
            value=pd.DataFrame(
                columns=["Symbol", "Timeframe", "Candles", "Earliest (UTC)", "Latest (UTC)"]
            ),
            label="Stored OHLCV",
            interactive=False,
        )
        overview_btn.click(
            fn=database_overview,
            inputs=[],
            outputs=[db_size_output, overview_output],
        )

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
