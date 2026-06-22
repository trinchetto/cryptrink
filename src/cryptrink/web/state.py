"""Process-wide runtime state for the Gradio web app.

The Gradio app boots once per Space process and reuses a single async
SQLAlchemy session factory across all tab handlers. This module owns that
singleton and registers the built-in strategies on first access.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import func, select

from cryptrink.core.config import load_config
from cryptrink.data.storage import OHLCV as OHLCVModel
from cryptrink.runtime import build_session_factory, ensure_builtins_registered

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from cryptrink.core.config import Settings


# Redesign UI state shared by every screen via the WebRuntime singleton.
LOG_BUFFER_MAX = 500
_VALID_MODES = ("paper", "live")
_lock = threading.Lock()


class LogEvent(NamedTuple):
    """One line in the docked global terminal.

    ``source`` is a short tag (sys / data / backtest / portfolio / live) used both
    for colour-coding and the terminal source filter; ``level`` is one of
    ok / info / warn / err and colours the message text.
    """

    time: str  # HH:MM:SS, UTC
    source: str
    level: str
    message: str


class Dataset(NamedTuple):
    """A persisted ``(symbol, timeframe)`` group with summary stats.

    Powers the Dataset dropdown that the Backtest, Suggest, and Live tabs
    seed from. Tabs select a Dataset rather than a free-text symbol so the
    timeframe travels with the symbol — keeping the UI consistent with what
    is actually stored in the OHLCV table.
    """

    symbol: str
    timeframe: str
    candle_count: int
    earliest: datetime
    latest: datetime

    @property
    def label(self) -> str:
        """Human-readable label rendered in dropdowns.

        Format: ``BTC-EUR @ 1h — 8023 candles (2024-01-01 → 2026-05-07)``.
        """
        return (
            f"{self.symbol} @ {self.timeframe} — {self.candle_count} candles "
            f"({self.earliest.date().isoformat()} → {self.latest.date().isoformat()})"
        )

    @property
    def value(self) -> str:
        """Stable dropdown value (``symbol|timeframe``).

        We use the value as the round-trip ID so handlers can split it back
        into ``(symbol, timeframe)`` without depending on label cosmetics.
        """
        return f"{self.symbol}|{self.timeframe}"

    @classmethod
    def parse(cls, value: str) -> tuple[str, str]:
        """Reverse of :attr:`value` — split a dropdown value back."""
        if "|" not in value:
            msg = f"Dataset value must be 'symbol|timeframe', got {value!r}"
            raise ValueError(msg)
        symbol, timeframe = value.split("|", 1)
        return symbol, timeframe


@dataclass
class WebRuntime:
    """Bundle of long-lived objects shared by every tab handler.

    ``cached_symbols`` holds the symbol vocabulary fetched from
    Revolut X's ``/configuration/pairs`` endpoint. Empty at boot — the
    Data tab's "Refresh symbols" button populates it. Every tab's
    Symbol dropdown reads :func:`get_symbol_choices` so they stay in
    sync after a refresh + page reload.
    """

    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    cached_symbols: list[str] = field(default_factory=list)
    # --- redesign UI state (global; single-operator Space) ---
    mode: str = "paper"
    log_buffer: deque[LogEvent] = field(
        default_factory=lambda: deque(maxlen=LOG_BUFFER_MAX)
    )
    last_synced: dict[str, str] = field(default_factory=dict)


_runtime: WebRuntime | None = None


def get_runtime() -> WebRuntime:
    """Return the process-wide :class:`WebRuntime`, initialising it lazily."""
    global _runtime
    if _runtime is None:
        ensure_builtins_registered()
        settings = load_config(None)
        session_factory = build_session_factory(settings.database.url)
        _runtime = WebRuntime(settings=settings, session_factory=session_factory)
    return _runtime


def reset_runtime() -> None:
    """Clear the cached runtime singleton.

    Tests use this to force re-initialisation against a fresh DB URL or to
    isolate module-level state between cases.
    """
    global _runtime
    _runtime = None


def get_symbol_choices() -> list[str]:
    """Return the dropdown vocabulary every tab's Symbol input seeds from.

    Order of preference:
    1. Symbols cached from a Revolut X ``/configuration/pairs`` refresh.
    2. ``settings.symbols`` from the loaded config.
    3. ``["BTC-EUR"]`` as a last-ditch default.
    """
    runtime = get_runtime()
    if runtime.cached_symbols:
        return list(runtime.cached_symbols)
    fallback = list(runtime.settings.symbols) if runtime.settings.symbols else []
    if not fallback:
        return ["BTC-EUR"]
    return fallback


def set_cached_symbols(symbols: list[str]) -> None:
    """Replace the live symbol cache with a fresh list."""
    runtime = get_runtime()
    runtime.cached_symbols = list(symbols)


def default_symbol() -> str:
    """Convenience: the symbol every tab's dropdown should select by default."""
    choices = get_symbol_choices()
    return choices[0] if choices else "BTC-EUR"


async def list_datasets() -> list[Dataset]:
    """Return one :class:`Dataset` per persisted ``(symbol, timeframe)`` group.

    Sorted by ``(symbol, timeframe)`` for predictable dropdown ordering.
    Tabs that read from the OHLCV table use this to populate their Dataset
    dropdown so the operator can only select something the database
    actually contains — matching the Data tab's "Database overview".
    """
    runtime = get_runtime()
    async with runtime.session_factory() as session:
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
        rows = list((await session.execute(stmt)).all())

    return [
        Dataset(
            symbol=row.symbol,
            timeframe=row.timeframe,
            candle_count=int(row.candle_count),
            earliest=datetime.fromtimestamp(int(row.earliest) / 1000, tz=UTC),
            latest=datetime.fromtimestamp(int(row.latest) / 1000, tz=UTC),
        )
        for row in rows
    ]


def list_datasets_sync() -> list[Dataset]:
    """Synchronous twin of :func:`list_datasets` for use during ``render()``.

    Gradio's tab ``render()`` is sync but ``list_datasets`` is async; without
    a sync path the dropdown is rendered with ``choices=[]`` and Gradio's
    SSR mode then rejects any value the operator picks before the dropdown
    has a chance to lazy-populate. Reading the OHLCV summary via stdlib
    ``sqlite3`` against the on-disk file is a cheap, dependency-free
    workaround — the table is small and we only need the GROUP BY summary.

    Returns ``[]`` for non-sqlite URLs (in-memory or other drivers); the
    caller should fall back to ``allow_custom_value=True`` in that case.
    """
    runtime = get_runtime()
    db_url = runtime.settings.database.url
    prefix = "sqlite+aiosqlite:///"
    if not db_url.startswith(prefix):
        return []
    raw = db_url[len(prefix) :]
    if raw == ":memory:":
        return []

    import sqlite3

    path = raw
    try:
        with sqlite3.connect(path) as conn:
            cursor = conn.execute(
                "SELECT symbol, timeframe, COUNT(*), MIN(timestamp), MAX(timestamp) "
                "FROM ohlcv "
                "GROUP BY symbol, timeframe "
                "ORDER BY symbol, timeframe"
            )
            rows = cursor.fetchall()
    except sqlite3.OperationalError:
        # Table doesn't exist yet (first boot before any backfill) or the
        # file is locked. Either way the dropdown should just be empty;
        # the operator can use the Refresh button after backfilling.
        return []

    return [
        Dataset(
            symbol=symbol,
            timeframe=timeframe,
            candle_count=int(count),
            earliest=datetime.fromtimestamp(int(earliest) / 1000, tz=UTC),
            latest=datetime.fromtimestamp(int(latest) / 1000, tz=UTC),
        )
        for symbol, timeframe, count, earliest, latest in rows
    ]


async def flush_runtime() -> None:
    """Dispose the runtime's SQLite engine and rebuild the session factory.

    SQLAlchemy's async engine pools connections internally. With a
    long-lived session factory those connections stay open across
    operations, which means the underlying ``.db`` file is never
    "closed" from the OS's point of view — and on FUSE-backed mounts
    like the HF Spaces Storage Bucket, that delays bucket replication
    until the next idle period.

    Calling this after a major write (backfill, wipe) does the
    minimum the operator can do from cryptrink to encourage the
    bucket to replicate before they restart the Space:

    1. Replace the runtime's :attr:`WebRuntime.session_factory` with a
       fresh one (so concurrent / subsequent callers can immediately
       open new connections without racing).
    2. Await ``engine.dispose()`` on the old engine, which closes the
       pool and releases all sqlite file handles.

    Any caller that grabbed the old factory before step 1 will keep
    using it until they're done — ``dispose()`` waits for those
    operations to drain.
    """
    runtime = get_runtime()
    old_engine = runtime.session_factory.kw["bind"]
    runtime.session_factory = build_session_factory(runtime.settings.database.url)
    await old_engine.dispose()


# ---------------------------------------------------------------------------
# Redesign UI state helpers (mode, shared log buffer, sync stamps)
#
# These mirror the get_symbol_choices / set_cached_symbols pattern: free
# functions over the WebRuntime singleton. The buffer and stamps are mutated
# under ``_lock`` because Gradio can serve handlers on a threadpool and a
# background live-loop worker may append log lines concurrently. They live on
# WebRuntime so ``reset_runtime()`` clears them between tests (xdist-safe).
# ---------------------------------------------------------------------------


def _now_hms() -> str:
    """Return the current UTC time as ``HH:MM:SS`` (terminal/stamp format)."""
    return datetime.now(UTC).strftime("%H:%M:%S")


def get_mode() -> str:
    """Return the active trading mode (``"paper"`` | ``"live"``)."""
    return get_runtime().mode


def set_mode(mode: str) -> None:
    """Set the active trading mode.

    Raises:
        ValueError: If ``mode`` is not ``"paper"`` or ``"live"``.
    """
    if mode not in _VALID_MODES:
        msg = f"mode must be one of {_VALID_MODES}, got {mode!r}"
        raise ValueError(msg)
    with _lock:
        get_runtime().mode = mode


def log_event(source: str, level: str, message: str) -> None:
    """Append one line to the shared docked-terminal buffer."""
    event = LogEvent(_now_hms(), source, level, message)
    with _lock:
        get_runtime().log_buffer.append(event)


def get_log_events(source_filter: str | None = None) -> list[LogEvent]:
    """Return buffered log events, optionally filtered by source.

    ``None`` / ``"all"`` returns everything; any other value keeps only events
    whose ``source`` matches (the terminal's source-filter chips pass this).
    """
    with _lock:
        events = list(get_runtime().log_buffer)
    if source_filter in (None, "all"):
        return events
    return [event for event in events if event.source == source_filter]


def clear_log_events() -> None:
    """Empty the shared log buffer (the terminal's ``clear`` action)."""
    with _lock:
        get_runtime().log_buffer.clear()


def mark_synced(key: str) -> None:
    """Record that ``key`` (e.g. ``"datasets"``) was auto-synced just now."""
    with _lock:
        get_runtime().last_synced[key] = _now_hms()


def get_last_synced(key: str) -> str | None:
    """Return the ``HH:MM:SS`` stamp for ``key``, or ``None`` if never synced."""
    return get_runtime().last_synced.get(key)
