"""Helpers that assemble the executor + data feed + notifier for the Live tab.

Kept out of :mod:`cryptrink.web.tabs.live` so the build logic is testable
without dragging gradio into the test suite. The Live tab calls
:func:`build_live_components` once per Start click; the returned bundle
plugs straight into :class:`cryptrink.web.live_loop.LiveLoop`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from cryptrink.core.logging import get_logger
from cryptrink.data.feed import HistoricalDataFeed, HybridDataFeed
from cryptrink.data.storage import OHLCVRepository

logger = get_logger(__name__)


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from cryptrink.core.config import Settings
    from cryptrink.data.feed import BaseDataFeed
    from cryptrink.execution.base import BaseExecutor
    from cryptrink.execution.engine import TradingEngine
    from cryptrink.notifications.discord import DiscordNotifier


class LiveMode(StrEnum):
    """User-selected execution mode for the Live tab's Start button."""

    PAPER = "paper"
    LIVE = "live"


@dataclass
class LiveComponents:
    """Bundle of per-Start objects the Live tab feeds into :class:`LiveLoop`.

    Attributes:
        engine: A started :class:`TradingEngine`. Caller must ``await
            engine.stop()`` via :attr:`cleanup`.
        data_feed: Read source for the loop's per-iteration candles.
        cleanup: Coroutine factory the loop's ``on_stop`` invokes; closes
            the engine, the exchange client (if any), and the notifier
            session in that order.
        mode: The mode that was actually built (may differ from the
            requested mode if Live was requested without credentials).
        notifier: Discord notifier when ``settings.notifications.discord_enabled``
            is set, otherwise None. The loop uses this to fire trade
            alerts from its ``on_signal`` callback.
    """

    engine: TradingEngine
    data_feed: BaseDataFeed
    cleanup: Callable[[], Awaitable[None]]
    mode: LiveMode
    notifier: DiscordNotifier | None = None


def has_revolutx_credentials(settings: Settings) -> bool:
    """True when REVOLUTX_API_KEY plus a private key (raw or PEM) are configured."""
    if not settings.revolutx.api_key.get_secret_value():
        return False
    if settings.revolutx.private_key.get_secret_value():
        return True
    return bool(settings.revolutx.private_key_path)


async def build_live_components(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    strategy: object,
    requested_mode: LiveMode,
    initial_balance: Decimal,
) -> LiveComponents:
    """Build the executor / engine / data-feed / cleanup tuple for a Start click.

    When ``requested_mode == LiveMode.LIVE`` and Revolut X credentials are
    present, this builds a :class:`LiveExecutor` against a live
    :class:`RevolutXExchange` connection and a :class:`HybridDataFeed`
    that pulls fresh candles from the exchange. Otherwise it falls back
    to the paper-mode bundle (PaperExecutor + HistoricalDataFeed) so the
    Start button never silently turns into real-money trading without
    explicit credentials.
    """
    from cryptrink.execution.engine import TradingEngine
    from cryptrink.execution.paper import PaperExecutor

    repository = OHLCVRepository(session_factory)

    actual_mode = requested_mode
    executor: BaseExecutor
    data_feed: BaseDataFeed
    exchange_close: Callable[[], Awaitable[None]] | None = None

    if requested_mode == LiveMode.LIVE and has_revolutx_credentials(settings):
        from cryptrink.exchange.revolutx import RevolutXExchange
        from cryptrink.execution.live import LiveExecutor

        private_key_b64 = settings.revolutx.get_private_key()
        exchange = RevolutXExchange(
            api_key=settings.revolutx.api_key.get_secret_value(),
            private_key_base64=private_key_b64,
            base_url=settings.revolutx.base_url,
        )
        await exchange.connect()
        executor = LiveExecutor(exchange_client=exchange)
        data_feed = HybridDataFeed(exchange=exchange, repository=repository)
        exchange_close = exchange.close
        logger.warning(
            "live_components_built",
            mode="live",
            message="Real-money trading mode is active",
        )
    else:
        if requested_mode == LiveMode.LIVE:
            logger.warning(
                "live_components_fallback_to_paper",
                reason="REVOLUTX_API_KEY or REVOLUTX_PRIVATE_KEY missing",
            )
        actual_mode = LiveMode.PAPER
        executor = PaperExecutor(initial_balance=initial_balance)
        data_feed = HistoricalDataFeed(repository)

    notifier = _build_notifier(settings)

    engine = TradingEngine(
        strategy=strategy,  # type: ignore[arg-type]
        executor=executor,
        session_factory=session_factory,
        initial_balance=initial_balance,
        risk_settings=settings.risk,
    )
    await engine.start()

    async def cleanup() -> None:
        try:
            await engine.stop()
        except Exception:
            logger.exception("live_engine_stop_failed")
        if exchange_close is not None:
            try:
                await exchange_close()
            except Exception:
                logger.exception("live_exchange_close_failed")
        if notifier is not None and notifier._session is not None:
            try:
                await notifier._session.close()
            except Exception:
                logger.exception("live_notifier_close_failed")

    return LiveComponents(
        engine=engine,
        data_feed=data_feed,
        cleanup=cleanup,
        mode=actual_mode,
        notifier=notifier,
    )


def _build_notifier(settings: Settings) -> DiscordNotifier | None:
    """Instantiate :class:`DiscordNotifier` when discord notifications are enabled."""
    notifications = settings.notifications
    if not notifications.discord_enabled:
        return None
    webhook = notifications.discord_webhook_url.get_secret_value()
    if not webhook:
        logger.warning(
            "discord_notifier_skipped",
            reason="NOTIFY_DISCORD_ENABLED is true but NOTIFY_DISCORD_WEBHOOK_URL is empty",
        )
        return None
    from cryptrink.notifications.discord import DiscordNotifier

    return DiscordNotifier(webhook_url=webhook, enabled=True)


__all__ = [
    "LiveComponents",
    "LiveMode",
    "build_live_components",
    "has_revolutx_credentials",
]
