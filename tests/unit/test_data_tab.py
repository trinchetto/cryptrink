"""Tests for the Data tab's overview + symbol-refresh helpers + size formatter.

The tab handlers use the WebRuntime singleton; we install a fresh
in-memory runtime per test via fixture so cases don't bleed state.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from pathlib import Path

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
    """Each test starts with a fresh in-memory DB and an empty symbol cache."""
    reset_runtime()
    yield
    reset_runtime()


def _settings(
    *,
    api_key: str = "",
    private_key: str = "",
    db_url: str = "sqlite+aiosqlite:///:memory:",
) -> Settings:
    return Settings(
        revolutx=RevolutXSettings(
            api_key=SecretStr(api_key),
            private_key=SecretStr(private_key),
        ),
        risk=RiskSettings(),
        database=DatabaseSettings(url=db_url),
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
    async def test_empty_db_returns_size_markdown_and_empty_frame(self) -> None:
        _install_runtime(_settings())
        size_md, df = await data_tab.database_overview()
        assert "in-memory" in size_md
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

        _, df = await data_tab.database_overview()
        assert list(df["Symbol"]) == ["BTC-EUR", "ETH-EUR"]
        assert list(df["Timeframe"]) == ["1h", "5m"]
        assert list(df["Candles"]) == [3, 5]
        for _, row in df.iterrows():
            assert row["Earliest (UTC)"] < row["Latest (UTC)"]


class TestFormatDbSize:
    def test_in_memory_url_renders_explanatory_message(self) -> None:
        result = data_tab._format_db_size("sqlite+aiosqlite:///:memory:")
        assert "in-memory" in result

    def test_non_sqlite_url_falls_back_gracefully(self) -> None:
        result = data_tab._format_db_size("postgresql+asyncpg://user@host/db")
        assert "not a sqlite file" in result

    def test_missing_file_reports_does_not_exist(self, tmp_path: Path) -> None:
        url = f"sqlite+aiosqlite:///{tmp_path / 'never_created.db'}"
        result = data_tab._format_db_size(url)
        assert "does not exist" in result

    def test_existing_file_reports_size_in_mb(self, tmp_path: Path) -> None:
        path = tmp_path / "existing.db"
        path.write_bytes(b"x" * (2 * 1024 * 1024 + 12345))  # ~2.01 MB
        url = f"sqlite+aiosqlite:///{path}"
        result = data_tab._format_db_size(url)
        # Two-decimal MB number, plus the path printed for the operator.
        assert "MB" in result
        assert str(path) in result
        assert "2.0" in result  # 2.01 or 2.00 depending on float math


class TestRefreshSymbols:
    @pytest.mark.asyncio
    async def test_no_creds_raises_friendly_error(self) -> None:
        _install_runtime(_settings())  # no creds
        with pytest.raises(gr.Error, match="credentials are not configured"):
            await data_tab.refresh_symbols("BTC-EUR")

    @pytest.mark.asyncio
    async def test_loads_symbols_and_caches_on_runtime(self) -> None:
        runtime = _install_runtime(
            _settings(
                api_key="abc",
                private_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            )
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

        assert update["choices"] == sorted(live_symbols)
        assert update["value"] == "BTC-EUR"
        assert "Loaded" in status and "4" in status
        # The runtime cache is now populated; other tabs see this on reload.
        assert runtime.cached_symbols == sorted(live_symbols)

    @pytest.mark.asyncio
    async def test_value_falls_back_to_first_when_current_missing(self) -> None:
        _install_runtime(
            _settings(
                api_key="abc",
                private_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            )
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

        assert update["value"] == "BTC-EUR"

    @pytest.mark.asyncio
    async def test_empty_response_raises(self) -> None:
        _install_runtime(
            _settings(
                api_key="abc",
                private_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            )
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
