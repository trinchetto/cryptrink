"""Tests for the Data tab's overview + symbol-refresh helpers.

The interactive button handlers use module-level singletons (the
WebRuntime, the cached symbol list); we reset them between tests via
fixture so each case starts from a known state.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

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
from cryptrink.web.state import WebRuntime, reset_runtime

gr = pytest.importorskip("gradio")  # data tab imports gradio at module load

from cryptrink.web.tabs import data as data_tab  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate() -> None:
    """Each test starts with a fresh in-memory DB + empty symbol cache."""
    reset_runtime()
    data_tab._cached_symbols = []
    yield
    reset_runtime()
    data_tab._cached_symbols = []


def _settings(*, api_key: str = "", private_key: str = "") -> Settings:
    return Settings(
        revolutx=RevolutXSettings(
            api_key=SecretStr(api_key),
            private_key=SecretStr(private_key),
        ),
        risk=RiskSettings(),
        database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
        notifications=NotificationSettings(),
    )


def _install_runtime(settings: Settings) -> WebRuntime:
    """Install a runtime backed by an in-memory DB so DB-touching helpers run."""
    session_factory = build_session_factory(settings.database.url)
    runtime = WebRuntime(settings=settings, session_factory=session_factory)
    web_state._runtime = runtime
    return runtime


class TestDatabaseOverview:
    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_frame_with_columns(self) -> None:
        _install_runtime(_settings())
        df = await data_tab.database_overview()
        assert df.empty
        assert list(df.columns) == [
            "Symbol",
            "Timeframe",
            "Candles",
            "Earliest (UTC)",
            "Latest (UTC)",
        ]

    @pytest.mark.asyncio
    async def test_groups_by_symbol_timeframe_and_reports_counts(self) -> None:
        runtime = _install_runtime(_settings())
        # Seed a few candles across two pairs so the GROUP BY collapses them.
        repo = OHLCVRepository(runtime.session_factory)
        from cryptrink.cli.utils import init_db_schema

        await init_db_schema(runtime.session_factory)
        await repo.save_batch(
            [
                {
                    "symbol": "BTC-EUR",
                    "timeframe": "1h",
                    "timestamp": 1_700_000_000_000 + i * 3_600_000,
                    "open": Decimal("100"),
                    "high": Decimal("110"),
                    "low": Decimal("90"),
                    "close": Decimal("105"),
                    "volume": Decimal("1"),
                }
                for i in range(3)
            ]
        )
        await repo.save_batch(
            [
                {
                    "symbol": "ETH-EUR",
                    "timeframe": "5m",
                    "timestamp": 1_700_000_000_000 + i * 300_000,
                    "open": Decimal("10"),
                    "high": Decimal("12"),
                    "low": Decimal("9"),
                    "close": Decimal("11"),
                    "volume": Decimal("2"),
                }
                for i in range(5)
            ]
        )

        df = await data_tab.database_overview()
        # Sorted by (symbol, timeframe).
        assert list(df["Symbol"]) == ["BTC-EUR", "ETH-EUR"]
        assert list(df["Timeframe"]) == ["1h", "5m"]
        assert list(df["Candles"]) == [3, 5]
        # Earliest < Latest (string-compare works for ISO-8601).
        for _, row in df.iterrows():
            assert row["Earliest (UTC)"] < row["Latest (UTC)"]


class TestRefreshSymbols:
    @pytest.mark.asyncio
    async def test_no_creds_raises_friendly_error(self) -> None:
        _install_runtime(_settings())  # no creds
        with pytest.raises(gr.Error, match="credentials are not configured"):
            await data_tab.refresh_symbols("BTC-EUR")

    @pytest.mark.asyncio
    async def test_loads_symbols_and_updates_dropdown(self) -> None:
        _install_runtime(
            _settings(api_key="abc", private_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        )

        live_symbols = ["BTC-EUR", "ETH-EUR", "SOL-EUR", "USDC-EUR"]
        with (
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.connect",
                new=AsyncMock(),
            ),
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.close",
                new=AsyncMock(),
            ),
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.get_symbols",
                new=AsyncMock(return_value=live_symbols),
            ),
        ):
            update, status = await data_tab.refresh_symbols("BTC-EUR")

        # Dropdown choices are sorted, value preserved when still in the list.
        assert update["choices"] == sorted(live_symbols)
        assert update["value"] == "BTC-EUR"
        assert "Loaded" in status and "4" in status
        # Module-level cache populated for follow-up renders.
        assert data_tab._cached_symbols == sorted(live_symbols)

    @pytest.mark.asyncio
    async def test_value_falls_back_to_first_when_current_missing(self) -> None:
        _install_runtime(
            _settings(api_key="abc", private_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        )

        live_symbols = ["BTC-EUR", "ETH-EUR"]
        with (
            patch("cryptrink.exchange.revolutx.RevolutXExchange.connect", new=AsyncMock()),
            patch("cryptrink.exchange.revolutx.RevolutXExchange.close", new=AsyncMock()),
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.get_symbols",
                new=AsyncMock(return_value=live_symbols),
            ),
        ):
            update, _ = await data_tab.refresh_symbols("DOGE-EUR")

        # "DOGE-EUR" isn't returned by the exchange; the dropdown falls
        # back to the first sorted symbol so the operator isn't stuck on
        # an unselectable value.
        assert update["value"] == "BTC-EUR"

    @pytest.mark.asyncio
    async def test_empty_response_raises(self) -> None:
        _install_runtime(
            _settings(api_key="abc", private_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        )
        with (
            patch("cryptrink.exchange.revolutx.RevolutXExchange.connect", new=AsyncMock()),
            patch("cryptrink.exchange.revolutx.RevolutXExchange.close", new=AsyncMock()),
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange.get_symbols",
                new=AsyncMock(return_value=[]),
            ),
            pytest.raises(gr.Error, match="empty symbol list"),
        ):
            await data_tab.refresh_symbols("BTC-EUR")


class TestInitialSymbolChoices:
    def test_uses_cached_symbols_when_available(self) -> None:
        data_tab._cached_symbols = ["BTC-EUR", "ETH-EUR", "SOL-EUR"]
        _install_runtime(_settings())
        assert data_tab._initial_symbol_choices("BTC-EUR") == [
            "BTC-EUR",
            "ETH-EUR",
            "SOL-EUR",
        ]

    def test_falls_back_to_settings_symbols(self) -> None:
        runtime = _install_runtime(_settings())
        runtime.settings.symbols = ["BTC-EUR", "ETH-EUR"]
        assert data_tab._initial_symbol_choices("BTC-EUR") == ["BTC-EUR", "ETH-EUR"]

    def test_inserts_default_when_missing_from_settings(self) -> None:
        runtime = _install_runtime(_settings())
        runtime.settings.symbols = ["ETH-EUR"]
        choices = data_tab._initial_symbol_choices("BTC-EUR")
        assert choices[0] == "BTC-EUR"
        assert "ETH-EUR" in choices
