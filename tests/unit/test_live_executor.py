"""Unit tests for LiveExecutor."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from cryptrink.exchange.base import Order, OrderSide, OrderStatus, OrderType
from cryptrink.execution.base import ExecutionContext
from cryptrink.execution.live import LiveExecutor
from cryptrink.strategies.base import Signal, SignalStrength, SignalType


@pytest.fixture
def mock_exchange():
    """Create a mock exchange client."""
    exchange = Mock()
    exchange.create_order = AsyncMock()
    exchange.cancel_order = AsyncMock()
    exchange.get_order = AsyncMock()
    exchange.get_open_orders = AsyncMock()
    return exchange


@pytest.fixture
def live_executor(mock_exchange):
    """Create a LiveExecutor with mocked exchange."""
    return LiveExecutor(exchange_client=mock_exchange)


@pytest.fixture
def execution_context():
    """Create a sample execution context."""
    return ExecutionContext(
        symbol="BTC-USD",
        current_price=Decimal("50000"),
        timestamp=datetime.now(UTC),
        account_balance=Decimal("10000"),
        available_balance=Decimal("10000"),
        has_position=False,
        position_size=Decimal("0"),
    )


@pytest.fixture
def buy_signal():
    """Create a sample buy signal."""
    return Signal(
        signal_type=SignalType.ENTRY_LONG,
        symbol="BTC-USD",
        timestamp=datetime.now(UTC),
        price=Decimal("50000"),
        strength=SignalStrength.STRONG,
    )


@pytest.fixture
def sell_signal():
    """Create a sample sell signal."""
    return Signal(
        signal_type=SignalType.EXIT_LONG,
        symbol="BTC-USD",
        timestamp=datetime.now(UTC),
        price=Decimal("50000"),
        strength=SignalStrength.STRONG,
    )


@pytest.fixture
def hold_signal():
    """Create a sample hold signal."""
    return Signal(
        signal_type=SignalType.HOLD,
        symbol="BTC-USD",
        timestamp=datetime.now(UTC),
        price=Decimal("50000"),
        strength=SignalStrength.WEAK,
    )


class TestLiveExecutor:
    """Tests for LiveExecutor class."""

    def test_initialization(self, live_executor):
        """Test that LiveExecutor initializes correctly."""
        assert live_executor._client is not None
        assert live_executor._order_tracking == {}

    async def test_execute_signal_hold(self, live_executor, hold_signal, execution_context):
        """Test that HOLD signals are ignored."""
        result = await live_executor.execute_signal(hold_signal, execution_context)

        assert result.success is False
        assert "HOLD" in result.message
        assert result.order_id is None
        live_executor._client.create_order.assert_not_called()

    async def test_execute_signal_buy_success(
        self, live_executor, mock_exchange, buy_signal, execution_context
    ):
        """Test successful buy order execution."""
        # Mock exchange response
        mock_order = Order(
            id="ORDER-123",
            client_order_id="",
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            quantity=Decimal("0.2"),
            filled_quantity=Decimal("0.2"),
            price=None,
            stop_price=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            trades=(),
        )
        mock_exchange.create_order.return_value = mock_order

        result = await live_executor.execute_signal(buy_signal, execution_context)

        assert result.success is True
        assert result.order_id == "ORDER-123"
        assert result.order_side == OrderSide.BUY
        assert result.status == OrderStatus.FILLED
        assert "ORDER-123" in live_executor._order_tracking

        # Verify exchange was called correctly
        mock_exchange.create_order.assert_called_once()
        call_kwargs = mock_exchange.create_order.call_args.kwargs
        assert call_kwargs["symbol"] == "BTC-USD"
        assert call_kwargs["side"] == OrderSide.BUY
        assert call_kwargs["order_type"] == OrderType.MARKET

    async def test_execute_signal_sell_success(
        self, live_executor, mock_exchange, sell_signal, execution_context
    ):
        """Test successful sell order execution."""
        # Update context to have a position
        execution_context.has_position = True
        execution_context.position_size = Decimal("0.5")

        # Mock exchange response
        mock_order = Order(
            id="ORDER-456",
            client_order_id="",
            symbol="BTC-USD",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            quantity=Decimal("0.5"),
            filled_quantity=Decimal("0.5"),
            price=None,
            stop_price=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            trades=(),
        )
        mock_exchange.create_order.return_value = mock_order

        result = await live_executor.execute_signal(sell_signal, execution_context)

        assert result.success is True
        assert result.order_id == "ORDER-456"
        assert result.order_side == OrderSide.SELL
        assert result.quantity == Decimal("0.5")

    async def test_execute_signal_validation_failure_invalid_quantity(
        self, live_executor, sell_signal, execution_context
    ):
        """Test that sell signal is rejected when no position exists (quantity becomes 0)."""
        result = await live_executor.execute_signal(sell_signal, execution_context)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        # When no position, quantity calculation returns 0, which fails quantity validation
        assert "Invalid quantity" in result.message
        live_executor._client.create_order.assert_not_called()

    async def test_execute_signal_exchange_error(
        self, live_executor, mock_exchange, buy_signal, execution_context
    ):
        """Test handling of exchange errors during order placement."""
        # Mock exchange error
        mock_exchange.create_order.side_effect = Exception("Exchange API error")

        result = await live_executor.execute_signal(buy_signal, execution_context)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert "execution failed" in result.message
        assert "Exchange API error" in result.error

    async def test_cancel_order_success(self, live_executor, mock_exchange):
        """Test successful order cancellation."""
        # Add order to tracking
        live_executor._order_tracking["ORDER-123"] = {
            "order_id": "ORDER-123",
            "status": OrderStatus.OPEN,
        }

        # Mock exchange response
        mock_cancelled_order = Order(
            id="ORDER-123",
            client_order_id="",
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            status=OrderStatus.CANCELLED,
            quantity=Decimal("0.2"),
            filled_quantity=Decimal("0"),
            price=None,
            stop_price=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            trades=(),
        )
        mock_exchange.cancel_order.return_value = mock_cancelled_order

        result = await live_executor.cancel_order("ORDER-123")

        assert result is True
        assert live_executor._order_tracking["ORDER-123"]["status"] == OrderStatus.CANCELLED
        mock_exchange.cancel_order.assert_called_once_with("ORDER-123")

    async def test_cancel_order_failure(self, live_executor, mock_exchange):
        """Test order cancellation failure."""
        # Mock exchange error
        mock_exchange.cancel_order.side_effect = Exception("Order not found")

        result = await live_executor.cancel_order("NONEXISTENT")

        assert result is False

    async def test_get_order_status_success(self, live_executor, mock_exchange):
        """Test getting order status from exchange."""
        # Mock exchange response
        mock_order = Order(
            id="ORDER-123",
            client_order_id="",
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            quantity=Decimal("0.2"),
            filled_quantity=Decimal("0.2"),
            price=None,
            stop_price=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            trades=(),
        )
        mock_exchange.get_order.return_value = mock_order

        status = await live_executor.get_order_status("ORDER-123")

        assert status == OrderStatus.FILLED
        mock_exchange.get_order.assert_called_once_with("ORDER-123")

    async def test_get_order_status_not_found(self, live_executor, mock_exchange):
        """Test getting status of non-existent order."""
        # Mock exchange error
        mock_exchange.get_order.side_effect = Exception("Order not found")

        with pytest.raises(KeyError, match="not found or inaccessible"):
            await live_executor.get_order_status("NONEXISTENT")

    async def test_sync_state_with_open_orders(self, live_executor, mock_exchange):
        """Test state synchronization with open orders."""
        # Add tracked orders
        live_executor._order_tracking["ORDER-123"] = {
            "order_id": "ORDER-123",
            "status": OrderStatus.PENDING,
        }
        live_executor._order_tracking["ORDER-456"] = {
            "order_id": "ORDER-456",
            "status": OrderStatus.PENDING,
        }

        # Mock exchange response
        mock_open_orders = [
            Order(
                id="ORDER-123",
                client_order_id="",
                symbol="BTC-USD",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                status=OrderStatus.OPEN,
                quantity=Decimal("0.2"),
                filled_quantity=Decimal("0"),
                price=None,
                stop_price=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                trades=(),
            ),
        ]
        mock_exchange.get_open_orders.return_value = mock_open_orders

        # Mock get_order for the second order
        mock_filled_order = Order(
            id="ORDER-456",
            client_order_id="",
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            quantity=Decimal("0.2"),
            filled_quantity=Decimal("0.2"),
            price=None,
            stop_price=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            trades=(),
        )
        mock_exchange.get_order.return_value = mock_filled_order

        await live_executor.sync_state()

        # Verify statuses were updated
        assert live_executor._order_tracking["ORDER-123"]["status"] == OrderStatus.OPEN
        assert live_executor._order_tracking["ORDER-456"]["status"] == OrderStatus.FILLED

    async def test_sync_state_handles_missing_orders(self, live_executor, mock_exchange):
        """Test state sync handles orders that can't be found."""
        # Add tracked order
        live_executor._order_tracking["ORDER-999"] = {
            "order_id": "ORDER-999",
            "status": OrderStatus.PENDING,
        }

        # Mock exchange responses
        mock_exchange.get_open_orders.return_value = []
        mock_exchange.get_order.side_effect = Exception("Order not found")

        # Should not raise exception
        await live_executor.sync_state()

        # Order should still be in tracking (just not updated)
        assert "ORDER-999" in live_executor._order_tracking

    async def test_quantity_calculation_buy(self, live_executor, execution_context):
        """Test quantity calculation for buy orders."""
        quantity = live_executor._calculate_quantity(
            execution_context,
            Signal(
                signal_type=SignalType.ENTRY_LONG,
                symbol="BTC-USD",
                timestamp=datetime.now(UTC),
                price=Decimal("50000"),
                strength=SignalStrength.STRONG,
            ),
            OrderSide.BUY,
        )

        # Should use 10% of balance: 10000 * 0.1 / 50000 = 0.02
        assert quantity == Decimal("0.02")

    async def test_quantity_calculation_sell(self, live_executor, execution_context):
        """Test quantity calculation for sell orders."""
        execution_context.has_position = True
        execution_context.position_size = Decimal("0.5")

        quantity = live_executor._calculate_quantity(
            execution_context,
            Signal(
                signal_type=SignalType.EXIT_LONG,
                symbol="BTC-USD",
                timestamp=datetime.now(UTC),
                price=Decimal("50000"),
                strength=SignalStrength.STRONG,
            ),
            OrderSide.SELL,
        )

        # Should use full position size
        assert quantity == Decimal("0.5")

    async def test_order_tracking_persists_metadata(
        self, live_executor, mock_exchange, buy_signal, execution_context
    ):
        """Test that order tracking stores all relevant metadata."""
        mock_order = Order(
            id="ORDER-123",
            client_order_id="",
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            quantity=Decimal("0.2"),
            filled_quantity=Decimal("0.2"),
            price=None,
            stop_price=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            trades=(),
        )
        mock_exchange.create_order.return_value = mock_order

        await live_executor.execute_signal(buy_signal, execution_context)

        tracked = live_executor._order_tracking["ORDER-123"]
        assert tracked["order_id"] == "ORDER-123"
        assert tracked["symbol"] == "BTC-USD"
        assert tracked["side"] == OrderSide.BUY
        assert tracked["signal_type"] == SignalType.ENTRY_LONG
        assert tracked["created_at"] is not None
