"""Tests for the shared symbol-cache helpers on :mod:`cryptrink.web.state`.

These helpers seed the Symbol dropdown on every tab; getting the
fall-back order wrong silently strands operators on a stale list, so the
order is asserted explicitly here.
"""

from __future__ import annotations

import pytest

from cryptrink.core.config import (
    DatabaseSettings,
    NotificationSettings,
    RevolutXSettings,
    RiskSettings,
    Settings,
)
from cryptrink.runtime import build_session_factory
from cryptrink.web import state as web_state
from cryptrink.web.state import (
    WebRuntime,
    default_symbol,
    flush_runtime,
    get_runtime,
    get_symbol_choices,
    reset_runtime,
    set_cached_symbols,
)


@pytest.fixture(autouse=True)
def _isolate() -> None:
    reset_runtime()
    yield
    reset_runtime()


def _install_runtime(*, symbols: list[str] | None = None) -> WebRuntime:
    settings = Settings(
        revolutx=RevolutXSettings(),
        risk=RiskSettings(),
        database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
        notifications=NotificationSettings(),
        symbols=symbols if symbols is not None else ["BTC-EUR", "ETH-EUR"],
    )
    runtime = WebRuntime(
        settings=settings,
        session_factory=build_session_factory(settings.database.url),
    )
    web_state._runtime = runtime
    return runtime


class TestGetSymbolChoices:
    def test_prefers_cached_over_settings(self) -> None:
        runtime = _install_runtime(symbols=["BTC-EUR", "ETH-EUR"])
        runtime.cached_symbols = ["AAVE-EUR", "BTC-EUR", "SOL-EUR"]
        assert get_symbol_choices() == ["AAVE-EUR", "BTC-EUR", "SOL-EUR"]

    def test_falls_back_to_settings_when_cache_empty(self) -> None:
        _install_runtime(symbols=["BTC-EUR", "ETH-EUR"])
        assert get_symbol_choices() == ["BTC-EUR", "ETH-EUR"]

    def test_falls_back_to_btc_eur_when_settings_symbols_empty(self) -> None:
        _install_runtime(symbols=[])
        assert get_symbol_choices() == ["BTC-EUR"]

    def test_returns_a_copy_so_callers_cant_mutate_state(self) -> None:
        runtime = _install_runtime()
        runtime.cached_symbols = ["BTC-EUR", "ETH-EUR"]
        choices = get_symbol_choices()
        choices.append("evil")
        assert runtime.cached_symbols == ["BTC-EUR", "ETH-EUR"]


class TestDefaultSymbol:
    def test_returns_first_choice(self) -> None:
        runtime = _install_runtime(symbols=["ETH-EUR", "BTC-EUR"])
        assert default_symbol() == "ETH-EUR"
        runtime.cached_symbols = ["AAVE-EUR", "ZEC-EUR"]
        assert default_symbol() == "AAVE-EUR"


class TestSetCachedSymbols:
    def test_replaces_runtime_cache(self) -> None:
        runtime = _install_runtime()
        runtime.cached_symbols = ["old"]
        set_cached_symbols(["BTC-EUR", "ETH-EUR", "SOL-EUR"])
        assert runtime.cached_symbols == ["BTC-EUR", "ETH-EUR", "SOL-EUR"]

    def test_stores_a_copy_so_caller_mutations_dont_leak(self) -> None:
        runtime = _install_runtime()
        source = ["BTC-EUR", "ETH-EUR"]
        set_cached_symbols(source)
        source.append("evil")
        assert runtime.cached_symbols == ["BTC-EUR", "ETH-EUR"]


class TestFlushRuntime:
    @pytest.mark.asyncio
    async def test_replaces_session_factory_and_disposes_old_engine(self) -> None:
        """Disposing the old engine + rebuilding the factory is the
        operator's primary "encourage the bucket to sync" lever after
        a write. The runtime must still work for follow-up reads after
        the flush — regression test for breakage there."""
        runtime = _install_runtime(symbols=["BTC-EUR"])
        old_factory = runtime.session_factory
        old_engine = old_factory.kw["bind"]

        await flush_runtime()

        # Factory is replaced and the old engine is disposed.
        assert runtime.session_factory is not old_factory
        assert runtime.session_factory.kw["bind"] is not old_engine
        # The new factory must be functional — open a session and run a
        # trivial query so we know the engine is wired.
        async with runtime.session_factory() as session:
            from sqlalchemy import text

            result = await session.execute(text("SELECT 1"))
            assert result.scalar_one() == 1

    @pytest.mark.asyncio
    async def test_flush_is_safe_on_a_freshly_initialised_runtime(self) -> None:
        """Even with no operations between init and flush, the helper
        must not raise (operator might click DB diagnostics + flush
        before any backfill)."""
        _install_runtime()
        await flush_runtime()
        runtime = get_runtime()
        # Subsequent reads still work.
        async with runtime.session_factory() as session:
            from sqlalchemy import text

            assert (await session.execute(text("SELECT 2"))).scalar_one() == 2
