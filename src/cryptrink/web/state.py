"""Process-wide runtime state for the Gradio web app.

The Gradio app boots once per Space process and reuses a single async
SQLAlchemy session factory across all tab handlers. This module owns that
singleton and registers the built-in strategies on first access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cryptrink.core.config import load_config
from cryptrink.runtime import build_session_factory, ensure_builtins_registered

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from cryptrink.core.config import Settings


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
