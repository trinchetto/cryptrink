"""Order manager for tracking order lifecycle and state.

This module provides the OrderManager class for managing orders throughout
their lifecycle, from creation to completion or cancellation.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cryptrink.core.logging import get_logger
from cryptrink.execution.base import OrderSide, OrderStatus, OrderType
from cryptrink.execution.models import Order, Trade
from cryptrink.execution.repository import OrderRepository, TradeRepository

logger = get_logger(__name__)


class OrderManager:
    """Manages order lifecycle and persistence.

    The OrderManager tracks orders from creation through execution,
    managing state transitions and coordinating with the database.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Initialize the order manager.

        Args:
            session_factory: SQLAlchemy async session factory.
        """
        self._session_factory = session_factory
        self._order_repo = OrderRepository(session_factory)
        self._trade_repo = TradeRepository(session_factory)

        logger.info("order_manager_initialized")

    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
        strategy_name: str | None = None,
        signal_type: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Order:
        """Create a new order.

        Args:
            symbol: Trading symbol.
            side: Order side (BUY or SELL).
            order_type: Order type (MARKET or LIMIT).
            quantity: Order quantity.
            price: Order price (required for LIMIT orders).
            strategy_name: Optional strategy that generated this order.
            signal_type: Optional signal type (entry_long, exit_long, etc.).
            metadata: Optional metadata dictionary.

        Returns:
            Created Order model.

        Raises:
            ValueError: If price is required but not provided.
        """
        if order_type == OrderType.LIMIT and price is None:
            raise ValueError("Price is required for LIMIT orders")

        # Generate order ID
        order_id = f"ORD-{uuid4().hex[:12].upper()}"

        # Create timestamp
        now = datetime.now(UTC)
        created_at_ms = int(now.timestamp() * 1000)

        # Create order model
        order = Order(
            order_id=order_id,
            exchange_order_id=None,
            symbol=symbol,
            side=side.value,
            order_type=order_type.value,
            status=OrderStatus.PENDING.value,
            quantity=str(quantity),
            filled_quantity="0",
            price=str(price) if price else None,
            average_fill_price=None,
            fee="0",
            fee_currency=None,
            created_at=created_at_ms,
            submitted_at=None,
            filled_at=None,
            cancelled_at=None,
            order_metadata=str(metadata) if metadata else None,
            strategy_name=strategy_name,
            signal_type=signal_type,
        )

        # Persist to database
        order = await self._order_repo.create(order)

        logger.info(
            "order_created",
            order_id=order_id,
            symbol=symbol,
            side=side.value,
            type=order_type.value,
            quantity=float(quantity),
        )

        return order

    async def update_order_status(
        self,
        order_id: str,
        status: OrderStatus,
        exchange_order_id: str | None = None,
    ) -> Order:
        """Update order status.

        Args:
            order_id: Order ID to update.
            status: New status.
            exchange_order_id: Optional exchange order ID.

        Returns:
            Updated Order model.

        Raises:
            ValueError: If order not found.
        """
        order = await self._order_repo.get_by_order_id(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")

        # Update status
        order.status = status.value

        # Set exchange order ID if provided
        if exchange_order_id:
            order.exchange_order_id = exchange_order_id

        # Update timestamps based on status
        now_ms = int(datetime.now(UTC).timestamp() * 1000)

        if status == OrderStatus.SUBMITTED and order.submitted_at is None:
            order.submitted_at = now_ms
        elif status == OrderStatus.FILLED and order.filled_at is None:
            order.filled_at = now_ms
        elif status == OrderStatus.CANCELLED and order.cancelled_at is None:
            order.cancelled_at = now_ms

        # Persist changes
        order = await self._order_repo.update(order)

        logger.info(
            "order_status_updated",
            order_id=order_id,
            old_status=order.status,
            new_status=status.value,
        )

        return order

    async def record_fill(
        self,
        order_id: str,
        trade_id: str | None = None,
        quantity: Decimal | None = None,
        price: Decimal | None = None,
        fee: Decimal = Decimal("0"),
        fee_currency: str | None = None,
        exchange_trade_id: str | None = None,
    ) -> tuple[Order, Trade]:
        """Record a fill (full or partial) for an order.

        Args:
            order_id: Order ID being filled.
            trade_id: Optional custom trade ID (generated if not provided).
            quantity: Quantity filled (uses remaining if not provided).
            price: Fill price (uses order price if not provided).
            fee: Fee charged for this fill.
            fee_currency: Currency of the fee.
            exchange_trade_id: Optional exchange trade ID.

        Returns:
            Tuple of (updated Order, created Trade).

        Raises:
            ValueError: If order not found or validation fails.
        """
        order = await self._order_repo.get_by_order_id(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")

        # Calculate fill details
        if quantity is None:
            # Fill remaining quantity
            quantity = order.quantity_decimal - order.filled_quantity_decimal

        if price is None:
            # Use order price or average fill price
            price = order.price_decimal or Decimal("0")

        if quantity <= 0:
            raise ValueError(f"Invalid fill quantity: {quantity}")

        # Generate trade ID if not provided
        if trade_id is None:
            trade_id = f"TRD-{uuid4().hex[:12].upper()}"

        # Create trade record
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        trade = Trade(
            trade_id=trade_id,
            order_id=order_id,
            exchange_trade_id=exchange_trade_id,
            symbol=order.symbol,
            side=order.side,
            quantity=str(quantity),
            price=str(price),
            fee=str(fee),
            fee_currency=fee_currency,
            executed_at=now_ms,
            trade_metadata=None,
        )

        trade = await self._trade_repo.create(trade)

        # Update order filled quantity
        new_filled = order.filled_quantity_decimal + quantity
        order.filled_quantity = str(new_filled)

        # Update average fill price
        if order.average_fill_price:
            old_avg = Decimal(order.average_fill_price)
            old_qty = order.filled_quantity_decimal - quantity
            new_avg = (old_avg * old_qty + price * quantity) / new_filled
            order.average_fill_price = str(new_avg)
        else:
            order.average_fill_price = str(price)

        # Update total fee
        order.fee = str(Decimal(order.fee) + fee)
        if fee_currency and not order.fee_currency:
            order.fee_currency = fee_currency

        # Update status based on fill
        if new_filled >= order.quantity_decimal:
            order.status = OrderStatus.FILLED.value
            order.filled_at = now_ms
        elif new_filled > 0:
            order.status = OrderStatus.PARTIALLY_FILLED.value

        # Persist changes
        order = await self._order_repo.update(order)

        logger.info(
            "order_filled",
            order_id=order_id,
            trade_id=trade_id,
            quantity=float(quantity),
            price=float(price),
            filled_quantity=float(new_filled),
            total_quantity=float(order.quantity_decimal),
            status=order.status,
        )

        return order, trade

    async def get_order(self, order_id: str) -> Order | None:
        """Get an order by ID.

        Args:
            order_id: Order ID to retrieve.

        Returns:
            Order if found, None otherwise.
        """
        return await self._order_repo.get_by_order_id(order_id)

    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        """Get all open orders.

        Args:
            symbol: Optional symbol filter.

        Returns:
            List of open orders.
        """
        return await self._order_repo.get_open_orders(symbol=symbol)

    async def get_trades_for_order(self, order_id: str) -> list[Trade]:
        """Get all trades for an order.

        Args:
            order_id: Order ID to get trades for.

        Returns:
            List of trades.
        """
        return await self._trade_repo.get_trades_for_order(order_id)

    async def cancel_order(self, order_id: str) -> Order:
        """Cancel an order.

        Args:
            order_id: Order ID to cancel.

        Returns:
            Updated Order model.

        Raises:
            ValueError: If order not found or cannot be cancelled.
        """
        order = await self._order_repo.get_by_order_id(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")

        # Check if order can be cancelled
        if order.status in [
            OrderStatus.FILLED.value,
            OrderStatus.CANCELLED.value,
            OrderStatus.REJECTED.value,
        ]:
            raise ValueError(f"Order {order_id} cannot be cancelled (status: {order.status})")

        # Update status
        order.status = OrderStatus.CANCELLED.value
        order.cancelled_at = int(datetime.now(UTC).timestamp() * 1000)

        # Persist changes
        order = await self._order_repo.update(order)

        logger.info("order_cancelled", order_id=order_id)

        return order
