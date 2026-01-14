"""Unit tests for OrderManager."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from cryptrink.execution.base import OrderSide, OrderStatus, OrderType
from cryptrink.execution.order_manager import OrderManager
from cryptrink.execution.repository import init_execution_db


@pytest.fixture
async def engine() -> AsyncEngine:
    """Create an in-memory SQLite engine for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_execution_db(engine)
    return engine


@pytest.fixture
async def order_manager(engine: AsyncEngine) -> OrderManager:
    """Create an OrderManager instance for testing."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return OrderManager(session_factory)


class TestOrderManager:
    """Tests for OrderManager class."""

    async def test_create_market_order(self, order_manager: OrderManager) -> None:
        """Test creating a market order."""
        order = await order_manager.create_order(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1.5"),
        )

        assert order.order_id.startswith("ORD-")
        assert order.symbol == "BTC-USD"
        assert order.side == "buy"
        assert order.order_type == "market"
        assert order.status == "pending"
        assert order.quantity_decimal == Decimal("1.5")
        assert order.filled_quantity_decimal == Decimal("0")
        assert order.price is None  # Market order has no price
        assert order.created_at > 0

    async def test_create_limit_order(self, order_manager: OrderManager) -> None:
        """Test creating a limit order."""
        order = await order_manager.create_order(
            symbol="ETH-USD",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            price=Decimal("3000"),
        )

        assert order.symbol == "ETH-USD"
        assert order.side == "sell"
        assert order.order_type == "limit"
        assert order.quantity_decimal == Decimal("10")
        assert order.price_decimal == Decimal("3000")

    async def test_create_limit_order_without_price_raises_error(
        self, order_manager: OrderManager
    ) -> None:
        """Test that creating a limit order without price raises error."""
        with pytest.raises(ValueError, match="Price is required"):
            await order_manager.create_order(
                symbol="BTC-USD",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
            )

    async def test_update_order_status(self, order_manager: OrderManager) -> None:
        """Test updating order status."""
        # Create order
        order = await order_manager.create_order(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        assert order.status == "pending"
        assert order.submitted_at is None

        # Update to submitted
        updated = await order_manager.update_order_status(
            order.order_id, OrderStatus.SUBMITTED, exchange_order_id="EX123"
        )

        assert updated.status == "submitted"
        assert updated.exchange_order_id == "EX123"
        assert updated.submitted_at is not None

    async def test_record_full_fill(self, order_manager: OrderManager) -> None:
        """Test recording a full fill."""
        # Create order
        order = await order_manager.create_order(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("2"),
        )

        # Record fill
        updated_order, trade = await order_manager.record_fill(
            order_id=order.order_id,
            quantity=Decimal("2"),
            price=Decimal("50000"),
            fee=Decimal("1.5"),
            fee_currency="USD",
        )

        # Check order
        assert updated_order.status == "filled"
        assert updated_order.filled_quantity_decimal == Decimal("2")
        assert updated_order.average_fill_price_decimal == Decimal("50000")
        assert updated_order.fee_decimal == Decimal("1.5")
        assert updated_order.fee_currency == "USD"
        assert updated_order.filled_at is not None

        # Check trade
        assert trade.trade_id.startswith("TRD-")
        assert trade.order_id == order.order_id
        assert trade.quantity_decimal == Decimal("2")
        assert trade.price_decimal == Decimal("50000")
        assert trade.fee_decimal == Decimal("1.5")

    async def test_record_partial_fills(self, order_manager: OrderManager) -> None:
        """Test recording multiple partial fills."""
        # Create order
        order = await order_manager.create_order(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("3"),
        )

        # First partial fill
        updated1, _trade1 = await order_manager.record_fill(
            order_id=order.order_id,
            quantity=Decimal("1"),
            price=Decimal("50000"),
        )

        assert updated1.status == "partially_filled"
        assert updated1.filled_quantity_decimal == Decimal("1")
        assert updated1.average_fill_price_decimal == Decimal("50000")

        # Second partial fill
        updated2, _trade2 = await order_manager.record_fill(
            order_id=order.order_id,
            quantity=Decimal("1"),
            price=Decimal("51000"),
        )

        assert updated2.status == "partially_filled"
        assert updated2.filled_quantity_decimal == Decimal("2")
        # Average: (50000 * 1 + 51000 * 1) / 2 = 50500  # noqa: ERA001
        assert updated2.average_fill_price_decimal == Decimal("50500")

        # Final fill
        updated3, _trade3 = await order_manager.record_fill(
            order_id=order.order_id,
            quantity=Decimal("1"),
            price=Decimal("49000"),
        )

        assert updated3.status == "filled"
        assert updated3.filled_quantity_decimal == Decimal("3")
        # Average: (50500 * 2 + 49000 * 1) / 3 = 50000  # noqa: ERA001
        assert updated3.average_fill_price_decimal == Decimal("50000")

        # Verify all trades are recorded
        trades = await order_manager.get_trades_for_order(order.order_id)
        assert len(trades) == 3

    async def test_get_order(self, order_manager: OrderManager) -> None:
        """Test retrieving an order."""
        # Create order
        order = await order_manager.create_order(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        # Retrieve order
        retrieved = await order_manager.get_order(order.order_id)

        assert retrieved is not None
        assert retrieved.order_id == order.order_id
        assert retrieved.symbol == "BTC-USD"

    async def test_get_nonexistent_order(self, order_manager: OrderManager) -> None:
        """Test retrieving a non-existent order returns None."""
        order = await order_manager.get_order("NONEXISTENT")
        assert order is None

    async def test_get_open_orders(self, order_manager: OrderManager) -> None:
        """Test getting open orders."""
        # Create orders with different statuses
        order1 = await order_manager.create_order(
            symbol="BTC-USD", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=Decimal("1")
        )

        order2 = await order_manager.create_order(
            symbol="ETH-USD", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=Decimal("1")
        )

        await order_manager.update_order_status(order1.order_id, OrderStatus.SUBMITTED)
        await order_manager.update_order_status(order2.order_id, OrderStatus.FILLED)

        # Get open orders (order1 is submitted, order2 is filled so not open)
        open_orders = await order_manager.get_open_orders()

        assert len(open_orders) == 1  # Only submitted order
        assert open_orders[0].order_id == order1.order_id
        assert open_orders[0].status == "submitted"

    async def test_get_open_orders_by_symbol(self, order_manager: OrderManager) -> None:
        """Test getting open orders filtered by symbol."""
        await order_manager.create_order(
            symbol="BTC-USD", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=Decimal("1")
        )

        await order_manager.create_order(
            symbol="ETH-USD", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=Decimal("1")
        )

        # Get open orders for BTC-USD
        btc_orders = await order_manager.get_open_orders(symbol="BTC-USD")

        assert len(btc_orders) == 1
        assert btc_orders[0].symbol == "BTC-USD"

    async def test_cancel_order(self, order_manager: OrderManager) -> None:
        """Test cancelling an order."""
        # Create order
        order = await order_manager.create_order(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        # Cancel order
        cancelled = await order_manager.cancel_order(order.order_id)

        assert cancelled.status == "cancelled"
        assert cancelled.cancelled_at is not None

    async def test_cancel_filled_order_raises_error(self, order_manager: OrderManager) -> None:
        """Test that cancelling a filled order raises error."""
        # Create and fill order
        order = await order_manager.create_order(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        await order_manager.record_fill(
            order_id=order.order_id, quantity=Decimal("1"), price=Decimal("50000")
        )

        # Try to cancel
        with pytest.raises(ValueError, match="cannot be cancelled"):
            await order_manager.cancel_order(order.order_id)

    async def test_cancel_nonexistent_order_raises_error(self, order_manager: OrderManager) -> None:
        """Test that cancelling a non-existent order raises error."""
        with pytest.raises(ValueError, match="not found"):
            await order_manager.cancel_order("NONEXISTENT")

    async def test_order_with_strategy_metadata(self, order_manager: OrderManager) -> None:
        """Test creating order with strategy information."""
        order = await order_manager.create_order(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            strategy_name="sma_crossover",
            signal_type="entry_long",
            metadata={"signal_strength": "strong", "sma_fast": 10},
        )

        assert order.strategy_name == "sma_crossover"
        assert order.signal_type == "entry_long"
        assert order.order_metadata is not None
