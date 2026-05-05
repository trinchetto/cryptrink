"""Discord webhook notifier for trade events."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Self

import aiohttp

from cryptrink.core.logging import get_logger

if TYPE_CHECKING:
    from cryptrink.execution.models import Order, Position

logger = get_logger(__name__)


class DiscordNotifier:
    """Discord webhook notifier for trade events.

    Sends formatted embeds to Discord webhook for:
    - Trade executions
    - Position opens/closes
    - Daily summaries
    - Errors and alerts
    """

    def __init__(self, webhook_url: str, enabled: bool = True) -> None:
        """Initialize Discord notifier.

        Args:
            webhook_url: Discord webhook URL.
            enabled: Whether notifications are enabled.
        """
        self._webhook_url = webhook_url
        self._enabled = enabled
        self._session: aiohttp.ClientSession | None = None
        self._last_notification_time = 0.0
        self._min_interval = 1.0  # Minimum 1 second between notifications

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit."""
        if self._session:
            await self._session.close()

    async def send_trade_notification(
        self,
        order: Order,
        position: Position | None = None,
    ) -> None:
        """Send notification for trade execution.

        Args:
            order: Executed order.
            position: Associated position (if any).
        """
        if not self._enabled:
            return

        color = 0x00FF00 if order.side == "buy" else 0xFF0000  # Green for buy, red for sell

        fields = [
            {"name": "Symbol", "value": order.symbol, "inline": True},
            {"name": "Side", "value": order.side.upper(), "inline": True},
            {"name": "Quantity", "value": f"{float(order.quantity):.8f}", "inline": True},
            {
                "name": "Price",
                "value": f"€{float(order.price):.2f}" if order.price else "MARKET",
                "inline": True,
            },
            {"name": "Status", "value": order.status.upper(), "inline": True},
        ]

        if order.filled_quantity:
            fields.append(
                {
                    "name": "Filled",
                    "value": f"{float(order.filled_quantity):.8f}",
                    "inline": True,
                }
            )

        if order.fee:
            fields.append(
                {
                    "name": "Fees",
                    "value": f"€{float(order.fee):.2f}",
                    "inline": True,
                }
            )

        title = f"{'🟢' if order.side == 'buy' else '🔴'} {order.side.upper()} Order {order.status.upper()}"
        description = f"Order for {order.symbol}"

        await self._send_embed(
            title=title,
            description=description,
            color=color,
            fields=fields,
        )

    async def send_position_closed(self, position: Position) -> None:
        """Send notification for position closure.

        Args:
            position: Closed position.
        """
        if not self._enabled:
            return

        pnl = Decimal(position.realized_pnl) if position.realized_pnl else Decimal("0")
        color = 0x00FF00 if pnl > 0 else 0xFF0000  # Green for profit, red for loss

        fields = [
            {"name": "Symbol", "value": position.symbol, "inline": True},
            {"name": "Side", "value": position.side.upper(), "inline": True},
            {"name": "P&L", "value": f"€{float(pnl):.2f}", "inline": True},
            {
                "name": "Entry Price",
                "value": f"€{float(position.entry_price):.2f}",
                "inline": True,
            },
            {
                "name": "Exit Price",
                "value": f"€{float(position.exit_price):.2f}" if position.exit_price else "—",
                "inline": True,
            },
            {"name": "Fees", "value": f"€{float(position.total_fees or 0):.2f}", "inline": True},
        ]

        title = f"{'💰' if pnl > 0 else '📉'} Position Closed"
        description = f"{position.symbol} position closed with {float(pnl):.2f} EUR P&L"

        await self._send_embed(
            title=title,
            description=description,
            color=color,
            fields=fields,
        )

    async def send_daily_summary(self, performance: dict[str, Any]) -> None:
        """Send daily performance summary.

        Args:
            performance: Performance metrics dictionary.
        """
        if not self._enabled:
            return

        fields = [
            {
                "name": "Total P&L",
                "value": f"€{performance.get('total_pnl', 0):.2f}",
                "inline": True,
            },
            {"name": "Win Rate", "value": f"{performance.get('win_rate', 0):.1f}%", "inline": True},
            {
                "name": "Total Trades",
                "value": str(performance.get("total_trades", 0)),
                "inline": True,
            },
        ]

        await self._send_embed(
            title="📊 Daily Summary",
            description="Today's trading performance",
            color=0x0099FF,  # Blue
            fields=fields,
        )

    async def send_error(self, error_msg: str, context: dict[str, Any]) -> None:
        """Send error notification.

        Args:
            error_msg: Error message.
            context: Additional context information.
        """
        if not self._enabled:
            return

        fields = [
            {"name": key, "value": str(value), "inline": True} for key, value in context.items()
        ]

        await self._send_embed(
            title="⚠️ Error",
            description=error_msg,
            color=0xFF0000,  # Red
            fields=fields,
        )

    async def send_circuit_breaker_alert(
        self,
        reason: str,
        metrics: dict[str, Any],
    ) -> None:
        """Send circuit breaker alert.

        Args:
            reason: Reason for circuit breaker activation.
            metrics: Current risk metrics.
        """
        if not self._enabled:
            return

        fields = [
            {"name": key, "value": str(value), "inline": True} for key, value in metrics.items()
        ]

        await self._send_embed(
            title="🚨 Circuit Breaker Activated",
            description=reason,
            color=0xFF0000,  # Red
            fields=fields,
        )

    async def _send_embed(
        self,
        title: str,
        description: str,
        color: int,
        fields: list[dict[str, Any]],
    ) -> None:
        """Send embed to Discord webhook.

        Args:
            title: Embed title.
            description: Embed description.
            color: Embed color (hex).
            fields: List of field dictionaries.
        """
        if not self._webhook_url or not self._enabled:
            return

        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - self._last_notification_time
        if time_since_last < self._min_interval:
            await asyncio.sleep(self._min_interval - time_since_last)

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "fields": fields,
            "footer": {"text": "Cryptrink Trading Agent"},
        }

        payload = {"embeds": [embed]}

        try:
            if not self._session:
                self._session = aiohttp.ClientSession()

            async with self._session.post(self._webhook_url, json=payload) as response:
                if response.status != 204:
                    logger.warning(
                        "discord_webhook_failed",
                        status=response.status,
                        response=await response.text(),
                    )
                else:
                    logger.debug("discord_notification_sent", title=title)
        except Exception as e:
            logger.warning("discord_notification_error", error=str(e))

        self._last_notification_time = time.time()
