"""Data tab for the Cryptrink Gradio web app.

Backfills the OHLCV table from Revolut X's ``/candles/{symbol}`` endpoint,
the only authoritative historical-candles source the exchange exposes.
The Backtest, Suggest, and Live tabs all read from the OHLCV table, so
this is the entry point for "I want real backtests, not the synthetic
seed".

UX: every action — backfill, delete a dataset, reset — emits one or
more lines into a shared terminal-style log at the bottom of the tab.
There are no per-section status panels; the running log is the only
output the operator needs to read. Backfill streams page-by-page
progress; everything else logs a Started / Completed pair so the
operator can see when a long DB op finishes.

The Symbol input is a Dropdown sourced from
:func:`cryptrink.web.state.get_symbol_choices`, auto-refreshed from
``/configuration/pairs`` every time this screen becomes visible. Other
tabs read the same cache so switching to this screen + a page reload
propagates the live vocabulary.
"""

from __future__ import annotations

import contextlib
import time
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
    flush_runtime,
    get_active_screen,
    get_runtime,
    get_symbol_choices,
    list_datasets_sync,
    log_event,
    set_cached_symbols,
)

# Browser-side confirm() so Wipe doesn't require a typed marker. If the
# operator clicks Cancel, the JS throws and Gradio aborts the call —
# the Python handler never runs, the terminal is unchanged.
_WIPE_CONFIRM_JS = """
(symbol, timeframe) => {
  const msg = `Wipe all OHLCV rows for ${symbol} ${timeframe}?\\n\\nThis cannot be undone.`;
  if (!confirm(msg)) {
    throw new Error('wipe cancelled by user');
  }
  return [symbol, timeframe];
}
"""

# Reset is more destructive than wipe (entire DB file gone, not just
# one (symbol, timeframe) group), so the prompt is more emphatic.
_RESET_CONFIRM_JS = """
() => {
  const msg = 'DELETE THE ENTIRE DATABASE FILE?\\n\\n'
            + 'Every stored OHLCV row will be permanently removed. '
            + 'Use this only if the database is corrupted '
            + '("database disk image is malformed") or you genuinely '
            + 'want to start from scratch.\\n\\nThis cannot be undone.';
  if (!confirm(msg)) {
    throw new Error('reset cancelled by user');
  }
  return [];
}
"""

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_SUPPORTED_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

# ----------------------------------------------------------------------
# Terminal log
# ----------------------------------------------------------------------
# Module-level shared log. Every Data tab handler appends to this and
# returns the rendered terminal so the bound Markdown component shows
# every action in one place.

_LOG: list[str] = []
_LOG_MAX_LINES = 200


def _now() -> str:
    """HH:MM:SS UTC for log line prefixes."""
    return datetime.now(UTC).strftime("%H:%M:%S")


def _emit(message: str) -> str:
    """Append ``message`` to the shared log and return the rendered terminal.

    The terminal caps at the most recent 200 lines so the markdown body
    doesn't grow unbounded.
    """
    _LOG.append(f"[{_now()}] {message}")
    if len(_LOG) > _LOG_MAX_LINES:
        del _LOG[: len(_LOG) - _LOG_MAX_LINES]
    # Mirror into the shared docked terminal so the global log carries every
    # Data tab action alongside the per-tab buffer the handlers still return.
    log_event("data", "info", message)
    return _render_terminal()


def _render_terminal() -> str:
    """Render the shared log as a markdown code block."""
    if not _LOG:
        return "```\n(empty terminal — click any button to log activity)\n```"
    return "```\n" + "\n".join(_LOG) + "\n```"


def _emit_failure(message: str, exc: Exception | None = None) -> str:
    """Convenience: log an error with type + message."""
    if exc is not None:
        return _emit(f"FAILED: {message} ({type(exc).__name__}: {exc})")
    return _emit(f"FAILED: {message}")


def _format_elapsed(start_perf: float) -> str:
    """Render elapsed time since ``start_perf`` (from ``time.perf_counter``)."""
    elapsed = time.perf_counter() - start_perf
    if elapsed < 1:
        return f"{elapsed * 1000:.0f}ms"
    return f"{elapsed:.2f}s"


# ----------------------------------------------------------------------
# DB / URL helpers
# ----------------------------------------------------------------------


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
    return Path(raw)


def _format_db_size(db_url: str) -> str:
    """Single-line rendering of the DB size for the log."""
    path = _sqlite_file_path(db_url)
    if path is None:
        if db_url.endswith(":memory:"):
            return "in-memory database (no on-disk size)"
        return f"DB URL is not a sqlite file ({db_url}); size unavailable"
    if not path.exists():
        return f"sqlite file `{path}` does not exist yet (will be created on first write)"
    size_mb = path.stat().st_size / (1024 * 1024)
    return f"sqlite file `{path}` is {size_mb:.2f} MB"


# ----------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------


async def backfill(
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> AsyncIterator[str]:
    """Stream backfill progress to the shared terminal."""
    yield _emit(f"backfill: validating inputs (symbol={symbol!r}, timeframe={timeframe!r})")

    if not symbol:
        yield _emit_failure("backfill: symbol is empty")
        return
    if not start_date:
        yield _emit_failure("backfill: start_date is empty")
        return

    runtime = get_runtime()
    if not has_revolutx_credentials(runtime.settings):
        yield _emit_failure(
            "backfill: REVOLUTX credentials not configured "
            "(set REVOLUTX_API_KEY + REVOLUTX_PRIVATE_KEY)"
        )
        return

    try:
        start_dt = _parse_date(start_date)
        end_dt = _parse_date(end_date, end_of_day=True) if end_date else datetime.now(UTC)
    except ValueError as exc:
        yield _emit_failure("backfill: invalid date", exc)
        return
    if end_dt <= start_dt:
        yield _emit_failure("backfill: end date must be after start date")
        return

    yield _emit(f"backfill: range {start_dt.isoformat()} → {end_dt.isoformat()} ({timeframe})")
    yield _emit("backfill: ensuring DB schema is initialised…")
    schema_started = time.perf_counter()
    await init_db_schema(runtime.session_factory)
    yield _emit(f"backfill: schema ready ({_format_elapsed(schema_started)})")

    from cryptrink.exchange.revolutx import RevolutXExchange, timeframe_to_interval_minutes

    try:
        timeframe_to_interval_minutes(timeframe)
    except ValueError as exc:
        yield _emit_failure("backfill: timeframe not supported by /candles", exc)
        return

    try:
        exchange = RevolutXExchange.from_settings(runtime.settings.revolutx)
    except ValueError as exc:
        yield _emit_failure("backfill: failed to load private key", exc)
        return

    since_ms = int(start_dt.timestamp() * 1000)
    until_ms = int(end_dt.timestamp() * 1000)

    yield _emit("backfill: connecting to Revolut X…")
    connect_started = time.perf_counter()
    try:
        await exchange.connect()
    except Exception as exc:
        yield _emit_failure("backfill: connect failed", exc)
        return
    yield _emit(f"backfill: connected ({_format_elapsed(connect_started)})")

    seen: set[int] = set()
    collected: list[dict[str, Any]] = []
    page_num = 0
    earliest_seen_ms: int | None = None
    fetch_started = time.perf_counter()
    fetch_failed = False

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
                page_earliest = int(page[0]["timestamp"])
                if earliest_seen_ms is None or page_earliest < earliest_seen_ms:
                    earliest_seen_ms = page_earliest
                earliest = datetime.fromtimestamp(page_earliest / 1000, tz=UTC)
                latest = datetime.fromtimestamp(int(page[-1]["timestamp"]) / 1000, tz=UTC)
                yield _emit(
                    f"backfill: page {page_num} • {len(page):>4} candles "
                    f"({new} new) • {earliest.isoformat(timespec='seconds')} → "
                    f"{latest.isoformat(timespec='seconds')}"
                )
        except Exception as exc:
            fetch_failed = True
            yield _emit_failure(f"backfill: page {page_num + 1} fetch failed", exc)
    finally:
        with contextlib.suppress(Exception):
            await exchange.close()
        yield _emit(
            f"backfill: pages exhausted in {_format_elapsed(fetch_started)} "
            f"({page_num} pages, {len(collected)} unique candles)"
        )

    # Distinguish termination reasons so the operator knows whether more
    # data exists upstream or whether the API simply has nothing older.
    if not fetch_failed:
        if earliest_seen_ms is None:
            yield _emit("backfill: stopped because Revolut X returned no candles for this range")
        elif earliest_seen_ms <= since_ms:
            iso = datetime.fromtimestamp(earliest_seen_ms / 1000, tz=UTC).isoformat(
                timespec="seconds"
            )
            yield _emit(f"backfill: stopped because requested start was reached ({iso})")
        elif page_num >= 50:
            iso = datetime.fromtimestamp(earliest_seen_ms / 1000, tz=UTC).isoformat(
                timespec="seconds"
            )
            yield _emit(
                f"backfill: stopped at the max_pages cap (50 pages); older history may "
                f"still be available — re-run with End={iso} to continue paging back"
            )
        else:
            iso = datetime.fromtimestamp(earliest_seen_ms / 1000, tz=UTC).isoformat(
                timespec="seconds"
            )
            yield _emit(
                f"backfill: stopped because Revolut X has no data older than {iso} "
                f"for {symbol} {timeframe}. Short timeframes (1m, 5m, 15m) are "
                "retained for only a limited window — use a coarser timeframe "
                "(1h, 4h, 1d) for longer history."
            )

    candles = sorted(
        (c for c in collected if since_ms <= int(c["timestamp"]) <= until_ms),
        key=lambda c: int(c["timestamp"]),
    )

    yield _emit(f"backfill: persisting {len(candles)} candles to OHLCV table…")
    persist_started = time.perf_counter()
    repository = OHLCVRepository(runtime.session_factory)
    saved = await repository.save_batch(candles) if candles else 0
    total = await _stored_count(symbol, timeframe)
    yield _emit(
        f"backfill: persisted {saved} candles in {_format_elapsed(persist_started)} "
        f"(total stored for {symbol} {timeframe}: {total})"
    )

    # Force-close all SQLite connections so the underlying file is
    # released to the OS. On FUSE-backed mounts (HF Spaces Storage
    # Bucket) this is the trigger the bucket usually needs to replicate
    # the latest .db file.
    yield _emit("backfill: flushing engine to release file handles for bucket sync…")
    flush_started = time.perf_counter()
    await flush_runtime()
    yield _emit(f"backfill: flush done ({_format_elapsed(flush_started)})")

    yield _emit(f"backfill: COMPLETE ({_format_db_size(runtime.settings.database.url)})")


async def wipe(symbol: str, timeframe: str) -> str:
    """Delete every OHLCV row for ``(symbol, timeframe)`` and log the outcome.

    Confirmation is gated browser-side via ``_WIPE_CONFIRM_JS``: if the
    operator clicks Cancel in the confirm dialog, the Gradio click is
    aborted before this Python handler runs, so we don't need a
    typed-DELETE input here.
    """
    if not symbol:
        return _emit_failure("wipe: symbol is empty")

    _emit(f"wipe: starting for {symbol} {timeframe}")
    runtime = get_runtime()
    started = time.perf_counter()
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

    # Same bucket-flush rationale as backfill — release file handles so
    # the FUSE mount can replicate the deletion.
    await flush_runtime()

    if deleted == 0:
        # Almost always a (symbol, timeframe) mismatch — operator left
        # the timeframe dropdown on its default and clicked Wipe.
        # Log loudly so the mismatch is obvious without scrolling up.
        return _emit(
            f"wipe: COMPLETE — NO ROWS matched {symbol} {timeframe}. "
            "Nothing was deleted. Check that the timeframe dropdown matches "
            "the data you actually want to wipe (click Database overview "
            "above to see what's stored)."
        )

    return _emit(
        f"wipe: COMPLETE — deleted {deleted} rows for {symbol} {timeframe} "
        f"in {_format_elapsed(started)} "
        f"({_format_db_size(runtime.settings.database.url)})"
    )


async def reset_database() -> str:
    """Delete the SQLite file and reinitialise the schema from scratch.

    Last-resort recovery for ``database disk image is malformed`` —
    SQLite cannot recover internally once a page is bad, so we close
    the engine, remove the main ``.db`` file plus any sidecars
    (``.db-journal``/``.db-wal``/``.db-shm``), then ask cryptrink to
    re-create the schema. The next backfill writes a fresh file.

    Only supports sqlite URLs. For non-file backends this returns a
    failure message rather than silently no-opping.
    """
    runtime = get_runtime()
    db_url = runtime.settings.database.url
    path = _sqlite_file_path(db_url)

    if path is None:
        return _emit_failure(
            f"reset: db url {db_url} is not a sqlite file (not implemented for "
            "non-sqlite backends — drop tables manually instead)"
        )

    _emit(f"reset: starting — target file is `{path}`")
    started = time.perf_counter()

    # Step 1: dispose the engine so SQLite releases the file handle.
    # flush_runtime also rebuilds session_factory; we'll re-init schema
    # against the fresh factory in step 3.
    await flush_runtime()
    _emit("reset: engine disposed (file handles released)")

    # Step 2: remove the main file plus every sidecar.
    removed: list[str] = []
    for suffix in ("", "-journal", "-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():  # noqa: ASYNC240
            try:
                sidecar.unlink()  # noqa: ASYNC240
                removed.append(sidecar.name)
            except OSError as exc:
                return _emit_failure(f"reset: failed to remove {sidecar.name}", exc)
    if removed:
        _emit(f"reset: removed {', '.join(removed)}")
    else:
        _emit("reset: nothing to remove (the file did not exist)")

    # Step 3: re-create the schema on the fresh factory.
    runtime = get_runtime()
    await init_db_schema(runtime.session_factory)
    _emit("reset: fresh schema initialised")

    return _emit(
        f"reset: COMPLETE in {_format_elapsed(started)} "
        f"({_format_db_size(runtime.settings.database.url)})"
    )


async def refresh_symbols(current: str) -> tuple[object, str]:
    """Pull the live symbol list from Revolut X and log + update the dropdown."""
    runtime = get_runtime()
    if not has_revolutx_credentials(runtime.settings):
        log = _emit_failure(
            "symbols: REVOLUTX credentials not configured "
            "(set REVOLUTX_API_KEY + REVOLUTX_PRIVATE_KEY)"
        )
        return gr.update(), log

    from cryptrink.exchange.revolutx import RevolutXExchange

    try:
        exchange = RevolutXExchange.from_settings(runtime.settings.revolutx)
    except ValueError as exc:
        return gr.update(), _emit_failure("symbols: failed to load private key", exc)

    _emit("symbols: connecting to Revolut X /configuration/pairs…")
    started = time.perf_counter()
    try:
        await exchange.connect()
    except Exception as exc:
        return gr.update(), _emit_failure("symbols: connect failed", exc)

    try:
        symbols: list[str]
        try:
            symbols = sorted(await exchange.get_symbols())
        except Exception as exc:
            return gr.update(), _emit_failure("symbols: get_symbols() failed", exc)
    finally:
        with contextlib.suppress(Exception):
            await exchange.close()

    if not symbols:
        return gr.update(), _emit_failure("symbols: API returned empty list")

    set_cached_symbols(symbols)
    new_value = current if current in symbols else symbols[0]
    log = _emit(
        f"symbols: COMPLETE — loaded {len(symbols)} symbols in {_format_elapsed(started)} "
        "(reload the page to update the dropdowns on other tabs)"
    )
    return gr.update(choices=symbols, value=new_value), log


def _stored_datasets_df() -> pd.DataFrame:
    """Snapshot the OHLCV table as a ``(symbol, timeframe)`` summary frame.

    Read synchronously via :func:`list_datasets_sync` so the Stored-datasets
    table lands populated on first render without a manual refresh button.
    """
    columns = ["Symbol", "Timeframe", "Candles", "Earliest", "Latest"]
    datasets = list_datasets_sync()
    if not datasets:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "Symbol": ds.symbol,
            "Timeframe": ds.timeframe,
            "Candles": ds.candle_count,
            "Earliest": ds.earliest.date().isoformat(),
            "Latest": ds.latest.date().isoformat(),
        }
        for ds in datasets
    ]
    return pd.DataFrame(rows, columns=columns)


_NO_SELECTION_LABEL = "_Click a row above to select a dataset to delete._"


def render() -> list[gr.Timer]:
    """Render the Data tab UI: Stored datasets, Backfill, then Advanced.

    Returns the screen-owned entry timer so the shell can gate it active only
    while this screen is visible (see :func:`_on_data_shown`).
    """
    runtime = get_runtime()
    creds_present = has_revolutx_credentials(runtime.settings)
    cred_hint = (
        "_Revolut X credentials detected — Backfill and the symbol auto-refresh will hit "
        "the live API._"
        if creds_present
        else "_Revolut X credentials missing; Backfill and the symbol auto-refresh will "
        "log an error until you configure them._"
    )

    # Seed the terminal with a one-time boot summary so the operator sees
    # which DB the tab is talking to before they click anything.
    if not _LOG:
        _emit(f"boot: {_format_db_size(runtime.settings.database.url)}")

    with gr.Row(elem_classes=["ck-screen-cols"]), gr.Column(elem_classes=["ck-col-main"]):
        # ---- 1: stored datasets (+ per-row delete) ----
        with gr.Group(elem_classes=["ck-card"]):
            gr.HTML('<div class="ck-card-title">Stored datasets</div>')
            gr.Markdown(
                "Auto-synced on startup. Revolut X's `/candles` endpoint keeps "
                "short timeframes (1m, 5m, 15m) for only a limited window — "
                "expect 1m to cover the most recent ~28 days. For longer "
                "history, use a coarser timeframe (1h, 4h, 1d)."
            )
            datasets_df = gr.Dataframe(value=_stored_datasets_df())
            selected_symbol = gr.Textbox(visible=False)
            selected_timeframe = gr.Textbox(visible=False)
            with gr.Row():
                selected_label = gr.Markdown(_NO_SELECTION_LABEL)
                delete_selected_btn = gr.Button(
                    "Delete selected dataset",
                    elem_classes=["ck-btn-stop"],
                    interactive=False,
                    scale=0,
                )

        # ---- 2: backfill configuration ----
        with gr.Group(elem_classes=["ck-card"]):
            gr.HTML('<div class="ck-section-label">Backfill</div>')
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
            start_input = gr.Textbox(value="2024-01-01", label="Start (YYYY-MM-DD)")
            end_input = gr.Textbox(value="", label="End (YYYY-MM-DD, blank = now)")
            backfill_btn = gr.Button("Backfill", elem_classes=["ck-btn-primary"])
            gr.Markdown(cred_hint)

        # ---- 3: advanced — the one truly destructive, whole-database action ----
        with gr.Accordion("Advanced", open=False):
            gr.Markdown(
                "Deletes the entire database file. Gated behind a browser confirm "
                "dialog. To remove a single dataset instead, select its row above."
            )
            reset_btn = gr.Button(
                "Reset database (corruption recovery)", elem_classes=["ck-btn-stop"]
            )

    # ``backfill``/``wipe``/``reset_database`` still return the rendered per-tab
    # terminal markdown; route it into a hidden component so they have a sink
    # while the visible log lives in the shared docked terminal.
    terminal = gr.Markdown(value=_render_terminal(), visible=False)

    # Backfill writes new rows — refresh the Stored-datasets table once the
    # stream completes so the operator sees the new (symbol, timeframe) group
    # without a manual refresh.
    backfill_btn.click(
        fn=backfill,
        inputs=[symbol_input, timeframe_input, start_input, end_input],
        outputs=[terminal],
    ).then(fn=_stored_datasets_df, inputs=[], outputs=[datasets_df])
    reset_btn.click(
        fn=reset_database,
        inputs=[],
        outputs=[terminal],
        js=_RESET_CONFIRM_JS,
    ).then(fn=_stored_datasets_df, inputs=[], outputs=[datasets_df])

    # ---- per-row delete: select a Stored-datasets row, then delete it ----
    def _on_dataset_row_select(evt: gr.SelectData) -> tuple[str, str, dict[str, Any], str]:
        if not evt.row_value:
            return "", "", gr.update(interactive=False), _NO_SELECTION_LABEL
        symbol, timeframe = str(evt.row_value[0]), str(evt.row_value[1])
        return (
            symbol,
            timeframe,
            gr.update(interactive=True),
            f"Selected: **{symbol} @ {timeframe}**",
        )

    datasets_df.select(
        fn=_on_dataset_row_select,
        inputs=[],
        outputs=[selected_symbol, selected_timeframe, delete_selected_btn, selected_label],
    )

    def _reset_selection() -> tuple[str, str, dict[str, Any], str]:
        return "", "", gr.update(interactive=False), _NO_SELECTION_LABEL

    delete_selected_btn.click(
        fn=wipe,
        inputs=[selected_symbol, selected_timeframe],
        outputs=[terminal],
        js=_WIPE_CONFIRM_JS,
    ).then(fn=_stored_datasets_df, inputs=[], outputs=[datasets_df]).then(
        fn=_reset_selection,
        inputs=[],
        outputs=[selected_symbol, selected_timeframe, delete_selected_btn, selected_label],
    )

    # ---- auto-refresh symbols once, every time this screen becomes visible ----
    # A self-deactivating Timer: the shell reactivates it (active=True) on every
    # nav click to "data" (see shell.py's ``_make_select``); the first tick fires
    # the refresh then flips itself back off, so it refreshes once per visit
    # rather than polling on an interval while the screen stays open.
    entry_timer = gr.Timer(0.3, active=False)

    async def _on_data_shown(current_symbol: str) -> tuple[object, object, object]:
        if get_active_screen() != "data":
            return gr.update(), gr.update(), gr.update()
        symbol_update, log_update = await refresh_symbols(current_symbol)
        return symbol_update, log_update, gr.update(active=False)

    entry_timer.tick(
        fn=_on_data_shown,
        inputs=[symbol_input],
        outputs=[symbol_input, terminal, entry_timer],
    )

    return [entry_timer]
