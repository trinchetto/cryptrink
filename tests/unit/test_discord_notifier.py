"""Unit tests for Discord notifier."""

import time
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from cryptrink.notifications.discord import DiscordNotifier


@pytest.fixture
def mock_session():
    """Create mock aiohttp ClientSession."""
    session = AsyncMock()
    response = AsyncMock()
    response.status = 204
    response.text = AsyncMock(return_value="")
    session.post.return_value.__aenter__.return_value = response
    return session


@pytest.fixture
def notifier():
    """Create Discord notifier instance."""
    return DiscordNotifier(
        webhook_url="https://discord.com/api/webhooks/test",
        enabled=True,
    )


class TestDiscordNotifierInit:
    """Tests for DiscordNotifier initialization."""

    def test_init_enabled(self):
        """Test initialization with enabled notifier."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            enabled=True,
        )

        assert notifier._webhook_url == "https://discord.com/api/webhooks/test"
        assert notifier._enabled is True
        assert notifier._session is None
        assert notifier._min_interval == 1.0

    def test_init_disabled(self):
        """Test initialization with disabled notifier."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            enabled=False,
        )

        assert notifier._enabled is False


class TestDiscordNotifierContextManager:
    """Tests for DiscordNotifier async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_creates_session(self):
        """Test context manager creates session."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            enabled=True,
        )

        async with notifier:
            assert notifier._session is not None

    @pytest.mark.asyncio
    async def test_context_manager_closes_session(self):
        """Test context manager closes session."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            enabled=True,
        )

        async with notifier:
            session = notifier._session
            session.close = AsyncMock()

        session.close.assert_called_once()


class TestSendTradeNotification:
    """Tests for send_trade_notification."""

    @pytest.mark.asyncio
    async def test_send_trade_notification_buy_order(self, notifier, mock_session):
        """Test sending notification for buy order."""
        notifier._session = mock_session

        order = Mock()
        order.symbol = "BTC-EUR"
        order.side = "buy"
        order.order_type = "market"
        order.quantity = Decimal("0.1")
        order.price = Decimal("50000.0")
        order.status = "filled"
        order.filled_quantity = Decimal("0.1")
        order.fee = Decimal("10.0")

        await notifier.send_trade_notification(order)

        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]

        assert "embeds" in payload
        assert len(payload["embeds"]) == 1
        embed = payload["embeds"][0]
        assert "BUY" in embed["title"]
        assert embed["color"] == 0x00FF00  # Green for buy

    @pytest.mark.asyncio
    async def test_send_trade_notification_sell_order(self, notifier, mock_session):
        """Test sending notification for sell order."""
        notifier._session = mock_session

        order = Mock()
        order.symbol = "ETH-EUR"
        order.side = "sell"
        order.order_type = "limit"
        order.quantity = Decimal("1.0")
        order.price = Decimal("3000.0")
        order.status = "filled"
        order.filled_quantity = None
        order.fee = None

        await notifier.send_trade_notification(order)

        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]

        embed = payload["embeds"][0]
        assert "SELL" in embed["title"]
        assert embed["color"] == 0xFF0000  # Red for sell

    @pytest.mark.asyncio
    async def test_send_trade_notification_disabled(self, mock_session):
        """Test notification not sent when disabled."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            enabled=False,
        )
        notifier._session = mock_session

        order = Mock()
        order.symbol = "BTC-EUR"
        order.side = "buy"
        order.status = "filled"

        await notifier.send_trade_notification(order)

        mock_session.post.assert_not_called()


class TestSendPositionClosed:
    """Tests for send_position_closed."""

    @pytest.mark.asyncio
    async def test_send_position_closed_profit(self, notifier, mock_session):
        """Test sending notification for profitable position."""
        notifier._session = mock_session

        position = Mock()
        position.symbol = "BTC-EUR"
        position.side = "long"
        position.entry_price = Decimal("50000.0")
        position.exit_price = Decimal("55000.0")
        position.realized_pnl = Decimal("500.0")
        position.total_fees = Decimal("10.0")

        await notifier.send_position_closed(position)

        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]

        embed = payload["embeds"][0]
        assert embed["color"] == 0x00FF00  # Green for profit
        assert "500.00" in embed["description"]

    @pytest.mark.asyncio
    async def test_send_position_closed_loss(self, notifier, mock_session):
        """Test sending notification for loss position."""
        notifier._session = mock_session

        position = Mock()
        position.symbol = "BTC-EUR"
        position.side = "short"
        position.entry_price = Decimal("50000.0")
        position.exit_price = Decimal("52000.0")
        position.realized_pnl = Decimal("-200.0")
        position.total_fees = Decimal("10.0")

        await notifier.send_position_closed(position)

        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]

        embed = payload["embeds"][0]
        assert embed["color"] == 0xFF0000  # Red for loss

    @pytest.mark.asyncio
    async def test_send_position_closed_disabled(self, mock_session):
        """Test notification not sent when disabled."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            enabled=False,
        )
        notifier._session = mock_session

        position = Mock()
        position.realized_pnl = Decimal("100.0")

        await notifier.send_position_closed(position)

        mock_session.post.assert_not_called()


class TestSendDailySummary:
    """Tests for send_daily_summary."""

    @pytest.mark.asyncio
    async def test_send_daily_summary(self, notifier, mock_session):
        """Test sending daily summary."""
        notifier._session = mock_session

        performance = {
            "total_pnl": 500.0,
            "win_rate": 65.5,
            "total_trades": 20,
        }

        await notifier.send_daily_summary(performance)

        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]

        embed = payload["embeds"][0]
        assert embed["title"] == "📊 Daily Summary"
        assert embed["color"] == 0x0099FF

    @pytest.mark.asyncio
    async def test_send_daily_summary_disabled(self, mock_session):
        """Test summary not sent when disabled."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            enabled=False,
        )
        notifier._session = mock_session

        performance = {"total_pnl": 0.0, "win_rate": 0.0, "total_trades": 0}

        await notifier.send_daily_summary(performance)

        mock_session.post.assert_not_called()


class TestSendError:
    """Tests for send_error."""

    @pytest.mark.asyncio
    async def test_send_error(self, notifier, mock_session):
        """Test sending error notification."""
        notifier._session = mock_session

        error_msg = "Test error occurred"
        context = {"symbol": "BTC-EUR", "action": "buy"}

        await notifier.send_error(error_msg, context)

        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]

        embed = payload["embeds"][0]
        assert embed["title"] == "⚠️ Error"
        assert embed["description"] == error_msg
        assert embed["color"] == 0xFF0000

    @pytest.mark.asyncio
    async def test_send_error_disabled(self, mock_session):
        """Test error not sent when disabled."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            enabled=False,
        )
        notifier._session = mock_session

        await notifier.send_error("Error", {})

        mock_session.post.assert_not_called()


class TestSendCircuitBreakerAlert:
    """Tests for send_circuit_breaker_alert."""

    @pytest.mark.asyncio
    async def test_send_circuit_breaker_alert(self, notifier, mock_session):
        """Test sending circuit breaker alert."""
        notifier._session = mock_session

        reason = "Max daily loss exceeded"
        metrics = {"daily_loss": -500.0, "threshold": -400.0}

        await notifier.send_circuit_breaker_alert(reason, metrics)

        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]

        embed = payload["embeds"][0]
        assert embed["title"] == "🚨 Circuit Breaker Activated"
        assert embed["description"] == reason
        assert embed["color"] == 0xFF0000

    @pytest.mark.asyncio
    async def test_send_circuit_breaker_alert_disabled(self, mock_session):
        """Test alert not sent when disabled."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            enabled=False,
        )
        notifier._session = mock_session

        await notifier.send_circuit_breaker_alert("Reason", {})

        mock_session.post.assert_not_called()


class TestRateLimiting:
    """Tests for rate limiting."""

    @pytest.mark.asyncio
    async def test_rate_limiting_enforced(self, notifier, mock_session):
        """Test rate limiting is enforced."""
        notifier._session = mock_session
        notifier._min_interval = 0.1  # 100ms for faster test

        order = Mock()
        order.symbol = "BTC-EUR"
        order.side = "buy"
        order.status = "filled"
        order.quantity = Decimal("0.1")
        order.price = None
        order.filled_quantity = None
        order.fee = None

        # Send two notifications rapidly
        start_time = time.time()
        await notifier.send_trade_notification(order)
        await notifier.send_trade_notification(order)
        elapsed = time.time() - start_time

        # Should take at least min_interval
        assert elapsed >= 0.1
        assert mock_session.post.call_count == 2


class TestWebhookFailure:
    """Tests for webhook failure handling."""

    @pytest.mark.asyncio
    async def test_webhook_failure_logged(self, notifier):
        """Test failed webhook is logged."""
        mock_session = AsyncMock()
        response = AsyncMock()
        response.status = 400
        response.text = AsyncMock(return_value="Bad Request")
        mock_session.post.return_value.__aenter__.return_value = response
        notifier._session = mock_session

        order = Mock()
        order.symbol = "BTC-EUR"
        order.side = "buy"
        order.status = "filled"
        order.quantity = Decimal("0.1")
        order.price = None
        order.filled_quantity = None
        order.fee = None

        # Should not raise exception
        await notifier.send_trade_notification(order)

        mock_session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_exception_handled(self, notifier):
        """Test exception during webhook is handled."""
        mock_session = AsyncMock()
        mock_session.post.side_effect = Exception("Network error")
        notifier._session = mock_session

        order = Mock()
        order.symbol = "BTC-EUR"
        order.side = "buy"
        order.status = "filled"
        order.quantity = Decimal("0.1")
        order.price = None
        order.filled_quantity = None
        order.fee = None

        # Should not raise exception
        await notifier.send_trade_notification(order)
