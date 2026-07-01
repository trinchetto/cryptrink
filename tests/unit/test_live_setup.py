"""Tests for :mod:`cryptrink.web.live_setup`."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from cryptrink.core.config import (
    DatabaseSettings,
    NotificationSettings,
    RevolutXSettings,
    RiskSettings,
    Settings,
)
from cryptrink.data.feed import HistoricalDataFeed, HybridDataFeed
from cryptrink.execution.live import LiveExecutor
from cryptrink.execution.paper import PaperExecutor
from cryptrink.web.live_setup import (
    LiveMode,
    build_live_components,
    has_revolutx_credentials,
)


def _settings(
    *,
    api_key: str = "",
    private_key: str = "",
    private_key_path: str | None = None,
    discord_enabled: bool = False,
    discord_webhook: str = "",
) -> Settings:
    """Build a Settings instance with the supplied secrets/flags."""
    return Settings(
        revolutx=RevolutXSettings(
            api_key=SecretStr(api_key),
            private_key=SecretStr(private_key),
            private_key_path=private_key_path,
        ),
        risk=RiskSettings(),
        database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
        notifications=NotificationSettings(
            discord_enabled=discord_enabled,
            discord_webhook_url=SecretStr(discord_webhook),
        ),
    )


class TestHasRevolutXCredentials:
    def test_false_when_api_key_missing(self) -> None:
        assert not has_revolutx_credentials(_settings())

    def test_false_when_only_api_key_set(self) -> None:
        assert not has_revolutx_credentials(_settings(api_key="abc"))

    def test_true_with_api_key_and_private_key(self) -> None:
        assert has_revolutx_credentials(_settings(api_key="abc", private_key="xyz"))

    def test_true_with_api_key_and_private_key_path(self) -> None:
        assert has_revolutx_credentials(_settings(api_key="abc", private_key_path="/some/path"))


class TestBuildLiveComponentsPaperMode:
    @pytest.mark.asyncio
    async def test_paper_mode_uses_paper_executor_and_historical_feed(self) -> None:
        settings = _settings()
        session_factory = MagicMock()
        strategy = MagicMock()

        with patch(
            "cryptrink.execution.engine.TradingEngine",
            autospec=False,
        ) as MockEngine:
            engine_inst = MagicMock()
            engine_inst.start = AsyncMock()
            engine_inst.stop = AsyncMock()
            MockEngine.return_value = engine_inst

            components = await build_live_components(
                settings=settings,
                session_factory=session_factory,
                strategy=strategy,
                requested_mode=LiveMode.PAPER,
                initial_balance=Decimal("10000"),
            )

        assert components.mode is LiveMode.PAPER
        assert isinstance(components.data_feed, HistoricalDataFeed)
        # The constructor was called with a PaperExecutor.
        kwargs = MockEngine.call_args.kwargs
        assert isinstance(kwargs["executor"], PaperExecutor)
        engine_inst.start.assert_awaited_once()
        # Cleanup must be safe even when there's no exchange to disconnect.
        await components.cleanup()
        engine_inst.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_live_mode_falls_back_to_paper_when_creds_missing(self) -> None:
        settings = _settings()  # no creds
        session_factory = MagicMock()
        strategy = MagicMock()

        with patch(
            "cryptrink.execution.engine.TradingEngine",
            autospec=False,
        ) as MockEngine:
            engine_inst = MagicMock()
            engine_inst.start = AsyncMock()
            engine_inst.stop = AsyncMock()
            MockEngine.return_value = engine_inst

            components = await build_live_components(
                settings=settings,
                session_factory=session_factory,
                strategy=strategy,
                requested_mode=LiveMode.LIVE,
                initial_balance=Decimal("10000"),
            )

        assert components.mode is LiveMode.PAPER  # fallback
        assert isinstance(components.data_feed, HistoricalDataFeed)
        kwargs = MockEngine.call_args.kwargs
        assert isinstance(kwargs["executor"], PaperExecutor)


class TestBuildLiveComponentsLiveMode:
    @pytest.mark.asyncio
    async def test_live_mode_with_creds_builds_live_executor_and_hybrid_feed(self) -> None:
        settings = _settings(api_key="abc", private_key="ZGVmYWtlcGtleQ==")
        session_factory = MagicMock()
        strategy = MagicMock()

        with (
            patch(
                "cryptrink.exchange.revolutx.RevolutXExchange",
                autospec=False,
            ) as MockExchange,
            patch(
                "cryptrink.execution.engine.TradingEngine",
                autospec=False,
            ) as MockEngine,
        ):
            exchange_inst = MagicMock()
            exchange_inst.connect = AsyncMock()
            exchange_inst.close = AsyncMock()
            # build_live_components constructs via the RevolutXExchange.from_settings factory.
            MockExchange.from_settings.return_value = exchange_inst

            engine_inst = MagicMock()
            engine_inst.start = AsyncMock()
            engine_inst.stop = AsyncMock()
            MockEngine.return_value = engine_inst

            components = await build_live_components(
                settings=settings,
                session_factory=session_factory,
                strategy=strategy,
                requested_mode=LiveMode.LIVE,
                initial_balance=Decimal("5000"),
            )

        assert components.mode is LiveMode.LIVE
        assert isinstance(components.data_feed, HybridDataFeed)
        kwargs = MockEngine.call_args.kwargs
        assert isinstance(kwargs["executor"], LiveExecutor)
        exchange_inst.connect.assert_awaited_once()
        # Cleanup must close the exchange client.
        await components.cleanup()
        exchange_inst.close.assert_awaited_once()


class TestNotifierBuilder:
    @pytest.mark.asyncio
    async def test_no_notifier_when_discord_disabled(self) -> None:
        settings = _settings(discord_enabled=False, discord_webhook="https://example.com")
        with patch("cryptrink.execution.engine.TradingEngine") as MockEngine:
            MockEngine.return_value = MagicMock(start=AsyncMock(), stop=AsyncMock())
            components = await build_live_components(
                settings=settings,
                session_factory=MagicMock(),
                strategy=MagicMock(),
                requested_mode=LiveMode.PAPER,
                initial_balance=Decimal("10000"),
            )
        assert components.notifier is None

    @pytest.mark.asyncio
    async def test_no_notifier_when_webhook_blank(self) -> None:
        settings = _settings(discord_enabled=True, discord_webhook="")
        with patch("cryptrink.execution.engine.TradingEngine") as MockEngine:
            MockEngine.return_value = MagicMock(start=AsyncMock(), stop=AsyncMock())
            components = await build_live_components(
                settings=settings,
                session_factory=MagicMock(),
                strategy=MagicMock(),
                requested_mode=LiveMode.PAPER,
                initial_balance=Decimal("10000"),
            )
        assert components.notifier is None

    @pytest.mark.asyncio
    async def test_notifier_present_when_enabled_with_webhook(self) -> None:
        settings = _settings(
            discord_enabled=True, discord_webhook="https://discord.example/webhook"
        )
        with patch("cryptrink.execution.engine.TradingEngine") as MockEngine:
            MockEngine.return_value = MagicMock(start=AsyncMock(), stop=AsyncMock())
            components = await build_live_components(
                settings=settings,
                session_factory=MagicMock(),
                strategy=MagicMock(),
                requested_mode=LiveMode.PAPER,
                initial_balance=Decimal("10000"),
            )
        assert components.notifier is not None
        # Cleanup must be tolerant of a notifier that never sent a message.
        await components.cleanup()
