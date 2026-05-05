"""Process-wide runtime state for the Gradio web app.

The Gradio app boots once per Space process and reuses a single async
SQLAlchemy session factory across all tab handlers. This module owns that
singleton and registers the built-in strategies on first access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cryptrink.core.config import load_config
from cryptrink.runtime import build_session_factory, ensure_builtins_registered

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from cryptrink.core.config import Settings


@dataclass
class WebRuntime:
    """Bundle of long-lived objects shared by every tab handler."""

    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]


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
