"""Repository classes for order and trade data access.

This module provides async repository classes for managing orders and trades
in the database, following the repository pattern from the data module.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cryptrink.core.logging import get_logger
from cryptrink.execution.models import Order, Trade

logger = get_logger(__name__)


class OrderRepository:
    """Repository for managing Order persistence.

    Provides async methods for creating, reading, updating, and querying orders.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Initialize the repository.

        Args:
            session_factory: SQLAlchemy async session factory.
        """
        self._session_factory = session_factory

    async def create(self, order: Order) -> Order:
        """Create a new order in the database.

        Args:
            order: Order model to create.

        Returns:
            The created order with ID assigned.
        """
        async with self._session_factory() as session:
            session.add(order)
            await session.commit()
            await session.refresh(order)
            logger.debug("order_created", order_id=order.order_id, symbol=order.symbol)
            return order

    async def get_by_order_id(self, order_id: str) -> Order | None:
        """Get an order by its order ID.

        Args:
            order_id: The order ID to search for.

        Returns:
            The order if found, None otherwise.
        """
        async with self._session_factory() as session:
            stmt = select(Order).where(Order.order_id == order_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_by_exchange_order_id(self, exchange_order_id: str) -> Order | None:
        """Get an order by its exchange order ID.

        Args:
            exchange_order_id: The exchange order ID to search for.

        Returns:
            The order if found, None otherwise.
        """
        async with self._session_factory() as session:
            stmt = select(Order).where(Order.exchange_order_id == exchange_order_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def update(self, order: Order) -> Order:
        """Update an existing order.

        Args:
            order: Order model with updated values.

        Returns:
            The updated order.
        """
        async with self._session_factory() as session:
            session.add(order)
            await session.commit()
            await session.refresh(order)
            logger.debug("order_updated", order_id=order.order_id, status=order.status)
            return order

    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        """Get all open orders (pending, submitted, partially_filled).

        Args:
            symbol: Optional symbol to filter by.

        Returns:
            List of open orders.
        """
        async with self._session_factory() as session:
            stmt = select(Order).where(
                Order.status.in_(["pending", "submitted", "partially_filled"])
            )
            if symbol:
                stmt = stmt.where(Order.symbol == symbol)
            stmt = stmt.order_by(Order.created_at.desc())

            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_orders_by_symbol(
        self,
        symbol: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Order]:
        """Get orders for a symbol within a time range.

        Args:
            symbol: Trading symbol.
            start_time: Optional start time filter.
            end_time: Optional end time filter.

        Returns:
            List of orders matching the criteria.
        """
        async with self._session_factory() as session:
            stmt = select(Order).where(Order.symbol == symbol)

            if start_time:
                start_ms = int(start_time.timestamp() * 1000)
                stmt = stmt.where(Order.created_at >= start_ms)

            if end_time:
                end_ms = int(end_time.timestamp() * 1000)
                stmt = stmt.where(Order.created_at <= end_ms)

            stmt = stmt.order_by(Order.created_at.desc())

            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_orders_by_status(
        self,
        status: str,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[Order]:
        """Get orders by status.

        Args:
            status: Order status to filter by.
            symbol: Optional symbol to filter by.
            limit: Maximum number of orders to return.

        Returns:
            List of orders with the specified status.
        """
        async with self._session_factory() as session:
            stmt = select(Order).where(Order.status == status)

            if symbol:
                stmt = stmt.where(Order.symbol == symbol)

            stmt = stmt.order_by(Order.created_at.desc()).limit(limit)

            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_recent_orders(self, limit: int = 50) -> list[Order]:
        """Get recent orders.

        Args:
            limit: Maximum number of orders to return.

        Returns:
            List of recent orders.
        """
        async with self._session_factory() as session:
            stmt = select(Order).order_by(Order.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())


class TradeRepository:
    """Repository for managing Trade persistence.

    Provides async methods for creating, reading, and querying trades.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Initialize the repository.

        Args:
            session_factory: SQLAlchemy async session factory.
        """
        self._session_factory = session_factory

    async def create(self, trade: Trade) -> Trade:
        """Create a new trade in the database.

        Args:
            trade: Trade model to create.

        Returns:
            The created trade with ID assigned.
        """
        async with self._session_factory() as session:
            session.add(trade)
            await session.commit()
            await session.refresh(trade)
            logger.debug(
                "trade_created",
                trade_id=trade.trade_id,
                order_id=trade.order_id,
                symbol=trade.symbol,
            )
            return trade

    async def get_by_trade_id(self, trade_id: str) -> Trade | None:
        """Get a trade by its trade ID.

        Args:
            trade_id: The trade ID to search for.

        Returns:
            The trade if found, None otherwise.
        """
        async with self._session_factory() as session:
            stmt = select(Trade).where(Trade.trade_id == trade_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_trades_for_order(self, order_id: str) -> list[Trade]:
        """Get all trades for a specific order.

        Args:
            order_id: The order ID to get trades for.

        Returns:
            List of trades for the order.
        """
        async with self._session_factory() as session:
            stmt = select(Trade).where(Trade.order_id == order_id).order_by(Trade.executed_at.asc())
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_trades_by_symbol(
        self,
        symbol: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Trade]:
        """Get trades for a symbol within a time range.

        Args:
            symbol: Trading symbol.
            start_time: Optional start time filter.
            end_time: Optional end time filter.

        Returns:
            List of trades matching the criteria.
        """
        async with self._session_factory() as session:
            stmt = select(Trade).where(Trade.symbol == symbol)

            if start_time:
                start_ms = int(start_time.timestamp() * 1000)
                stmt = stmt.where(Trade.executed_at >= start_ms)

            if end_time:
                end_ms = int(end_time.timestamp() * 1000)
                stmt = stmt.where(Trade.executed_at <= end_ms)

            stmt = stmt.order_by(Trade.executed_at.desc())

            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_recent_trades(self, limit: int = 50) -> list[Trade]:
        """Get recent trades.

        Args:
            limit: Maximum number of trades to return.

        Returns:
            List of recent trades.
        """
        async with self._session_factory() as session:
            stmt = select(Trade).order_by(Trade.executed_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())


async def init_execution_db(engine: AsyncEngine) -> None:
    """Initialize execution database tables.

    Args:
        engine: SQLAlchemy async engine.
    """
    from cryptrink.data.storage import Base

    async with engine.begin() as conn:
        # Create all tables defined in Base
        await conn.run_sync(Base.metadata.create_all)
        logger.info("execution_tables_initialized")
