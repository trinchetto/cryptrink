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


class _FakePost:
    """Minimal async-context-manager fake for ``aiohttp.ClientSession.post``.

    The existing ``mock_session`` fixture wires
    ``session.post.return_value.__aenter__.return_value`` which only
    works inside callers that swallow exceptions — the actual ``async
    with`` blows up because ``AsyncMock.post(...)`` returns a coroutine,
    not a context manager. ``send_test`` doesn't swallow, so we need a
    real one. Capturing ``call_args`` lets us assert the payload too.
    """

    def __init__(self, status: int, body: str = "") -> None:
        self._status = status
        self._body = body
        self.call_args: tuple[tuple, dict] | None = None
        self.called = False

    def __call__(self, *args, **kwargs):
        self.call_args = (args, kwargs)
        self.called = True
        outer = self

        class _Ctx:
            async def __aenter__(self_inner):
                response = AsyncMock()
                response.status = outer._status
                response.text = AsyncMock(return_value=outer._body)
                return response

            async def __aexit__(self_inner, exc_type, exc, tb):
                return None

        return _Ctx()


class _FakeSession:
    def __init__(self, post: _FakePost) -> None:
        self.post = post

    async def close(self) -> None:  # pragma: no cover — no-op
        return None


class TestDiscordSendTest:
    """``DiscordNotifier.send_test`` powers the Live tab's "Test Discord
    notification" button. Unlike the trade-notification path it must
    *surface* the HTTP status / body so the operator sees why the
    webhook is misconfigured (revoked, deleted, etc.)."""

    @pytest.mark.asyncio
    async def test_returns_ok_when_webhook_returns_204(self, notifier):
        post = _FakePost(status=204, body="")
        notifier._session = _FakeSession(post)  # type: ignore[assignment]
        result = await notifier.send_test()
        assert result.ok is True
        assert result.status == 204
        assert "delivered" in result.detail.lower()
        assert post.called
        # Payload must include the test embed.
        kwargs = post.call_args[1]
        assert "embeds" in kwargs["json"]
        assert kwargs["json"]["embeds"][0]["title"].startswith("🧪")

    @pytest.mark.asyncio
    async def test_surfaces_non_204_status_and_body(self, notifier):
        """A revoked webhook returns 401 — the test handler should expose
        both the status code and the response body verbatim so the
        operator can see Discord's reason."""
        post = _FakePost(status=401, body='{"message":"Unauthorized","code":50027}')
        notifier._session = _FakeSession(post)  # type: ignore[assignment]
        result = await notifier.send_test()
        assert result.ok is False
        assert result.status == 401
        assert "Unauthorized" in result.detail

    @pytest.mark.asyncio
    async def test_returns_failure_when_webhook_url_empty(self):
        notifier = DiscordNotifier(webhook_url="", enabled=True)
        result = await notifier.send_test()
        assert result.ok is False
        assert result.status == 0
        assert "empty" in result.detail.lower()

    @pytest.mark.asyncio
    async def test_runs_even_when_notifier_is_disabled(self):
        """The operator hit the explicit test button — bypass the
        ``enabled`` gate so the probe always actually fires."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test", enabled=False
        )
        post = _FakePost(status=204)
        notifier._session = _FakeSession(post)  # type: ignore[assignment]
        result = await notifier.send_test()
        assert result.ok is True
        assert post.called
