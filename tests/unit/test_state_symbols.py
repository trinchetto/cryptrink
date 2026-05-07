"""Tests for the shared symbol-cache helpers on :mod:`cryptrink.web.state`.

These helpers seed the Symbol dropdown on every tab; getting the
fall-back order wrong silently strands operators on a stale list, so the
order is asserted explicitly here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cryptrink.core.config import (
    DatabaseSettings,
    NotificationSettings,
    RevolutXSettings,
    RiskSettings,
    Settings,
)
from cryptrink.data.storage import OHLCVRepository
from cryptrink.runtime import build_session_factory
from cryptrink.web import state as web_state
from cryptrink.web.state import (
    Dataset,
    WebRuntime,
    default_symbol,
    flush_runtime,
    get_runtime,
    get_symbol_choices,
    list_datasets,
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


class TestDatasetValueRoundTrip:
    """The dropdown value/label format is part of the public API of the
    Dataset namedtuple. Tabs decode the value back into ``(symbol,
    timeframe)`` without parsing the (cosmetic) label."""

    def test_value_is_pipe_delimited(self) -> None:
        ds = Dataset(
            symbol="BTC-EUR",
            timeframe="1h",
            candle_count=42,
            earliest=datetime(2024, 1, 1, tzinfo=UTC),
            latest=datetime(2024, 1, 2, tzinfo=UTC),
        )
        assert ds.value == "BTC-EUR|1h"

    def test_label_includes_count_and_dates(self) -> None:
        ds = Dataset(
            symbol="ETH-EUR",
            timeframe="5m",
            candle_count=10_000,
            earliest=datetime(2024, 1, 1, tzinfo=UTC),
            latest=datetime(2024, 5, 7, tzinfo=UTC),
        )
        assert "ETH-EUR" in ds.label
        assert "5m" in ds.label
        assert "10000 candles" in ds.label
        assert "2024-01-01" in ds.label
        assert "2024-05-07" in ds.label

    def test_parse_round_trips(self) -> None:
        symbol, tf = Dataset.parse("BTC-EUR|1h")
        assert symbol == "BTC-EUR"
        assert tf == "1h"

    def test_parse_rejects_bad_value(self) -> None:
        with pytest.raises(ValueError, match=r"symbol\|timeframe"):
            Dataset.parse("no-pipe-here")


class TestListDatasets:
    """``list_datasets`` powers the Dataset dropdown on Backtest, Suggest,
    and Live. It must reflect the live OHLCV table."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_data(self) -> None:
        _install_runtime()
        # Initialise schema so the query has a table to read.
        runtime = get_runtime()
        from cryptrink.cli.utils import init_db_schema

        await init_db_schema(runtime.session_factory)
        assert await list_datasets() == []

    @pytest.mark.asyncio
    async def test_groups_by_symbol_and_timeframe(self) -> None:
        _install_runtime()
        runtime = get_runtime()
        from cryptrink.cli.utils import init_db_schema

        await init_db_schema(runtime.session_factory)

        repo = OHLCVRepository(runtime.session_factory)
        # Two rows of BTC-EUR/1h, one row of ETH-EUR/5m.
        base = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
        await repo.save_batch(
            [
                {
                    "symbol": "BTC-EUR",
                    "timeframe": "1h",
                    "timestamp": base,
                    "open": Decimal("100"),
                    "high": Decimal("105"),
                    "low": Decimal("95"),
                    "close": Decimal("100"),
                    "volume": Decimal("1"),
                },
                {
                    "symbol": "BTC-EUR",
                    "timeframe": "1h",
                    "timestamp": base + 3_600_000,
                    "open": Decimal("100"),
                    "high": Decimal("105"),
                    "low": Decimal("95"),
                    "close": Decimal("101"),
                    "volume": Decimal("1"),
                },
                {
                    "symbol": "ETH-EUR",
                    "timeframe": "5m",
                    "timestamp": base,
                    "open": Decimal("3"),
                    "high": Decimal("4"),
                    "low": Decimal("2"),
                    "close": Decimal("3"),
                    "volume": Decimal("1"),
                },
            ]
        )

        datasets = await list_datasets()
        assert len(datasets) == 2
        # Sorted by (symbol, timeframe).
        assert datasets[0].symbol == "BTC-EUR"
        assert datasets[0].timeframe == "1h"
        assert datasets[0].candle_count == 2
        assert datasets[1].symbol == "ETH-EUR"
        assert datasets[1].timeframe == "5m"
        assert datasets[1].candle_count == 1
        # Timestamps are real UTC datetimes, not ints.
        assert isinstance(datasets[0].earliest, datetime)
        assert datasets[0].earliest.tzinfo is not None
