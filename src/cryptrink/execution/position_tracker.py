"""Position tracker for managing trading positions and P&L.

This module provides the PositionTracker class for tracking open and closed
positions, calculating realized and unrealized P&L, and managing position history.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cryptrink.core.logging import get_logger
from cryptrink.execution.models import Position
from cryptrink.execution.repository import PositionRepository

logger = get_logger(__name__)


class PositionTracker:
    """Tracks positions and calculates P&L.

    The PositionTracker manages position lifecycle from opening to closing,
    calculating realized and unrealized P&L, and maintaining position history.
    Uses FIFO (First In, First Out) accounting for partial position closes.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Initialize the position tracker.

        Args:
            session_factory: SQLAlchemy async session factory.
        """
        self._session_factory = session_factory
        self._position_repo = PositionRepository(session_factory)

        logger.info("position_tracker_initialized")

    async def open_position(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        entry_price: Decimal,
        entry_order_id: str,
        fee: Decimal = Decimal("0"),
        fee_currency: str | None = None,
        strategy_name: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Position:
        """Open a new position.

        Args:
            symbol: Trading symbol.
            side: Position side (long or short).
            quantity: Position quantity.
            entry_price: Entry price.
            entry_order_id: Order ID that opened this position.
            fee: Entry fee.
            fee_currency: Currency of the fee.
            strategy_name: Optional strategy that opened this position.
            metadata: Optional metadata dictionary.

        Returns:
            Created Position model.
        """
        # Generate position ID
        position_id = f"POS-{uuid4().hex[:12].upper()}"

        # Create timestamp
        now = datetime.now(UTC)
        opened_at_ms = int(now.timestamp() * 1000)

        # Create position model
        position = Position(
            position_id=position_id,
            symbol=symbol,
            side=side,
            status="open",
            quantity=str(quantity),
            entry_price=str(entry_price),
            exit_price=None,
            realized_pnl="0",
            unrealized_pnl="0",
            total_fees=str(fee),
            fee_currency=fee_currency,
            opened_at=opened_at_ms,
            closed_at=None,
            entry_order_id=entry_order_id,
            exit_order_id=None,
            strategy_name=strategy_name,
            position_metadata=str(metadata) if metadata else None,
        )

        # Persist to database
        position = await self._position_repo.create(position)

        logger.info(
            "position_opened",
            position_id=position_id,
            symbol=symbol,
            side=side,
            quantity=float(quantity),
            entry_price=float(entry_price),
        )

        return position

    async def close_position(
        self,
        position_id: str,
        exit_price: Decimal,
        exit_order_id: str,
        fee: Decimal = Decimal("0"),
    ) -> Position:
        """Close an existing position.

        Args:
            position_id: Position ID to close.
            exit_price: Exit price.
            exit_order_id: Order ID that closed this position.
            fee: Exit fee.

        Returns:
            Updated Position model.

        Raises:
            ValueError: If position not found or already closed.
        """
        position = await self._position_repo.get_by_position_id(position_id)
        if not position:
            raise ValueError(f"Position {position_id} not found")

        if position.status == "closed":
            raise ValueError(f"Position {position_id} is already closed")

        # Calculate realized P&L
        quantity = position.quantity_decimal
        entry_price = position.entry_price_decimal

        if position.side == "long":
            # Long: profit when price goes up
            pnl = (exit_price - entry_price) * quantity
        else:
            # Short: profit when price goes down
            pnl = (entry_price - exit_price) * quantity

        # Update position
        position.status = "closed"
        position.exit_price = str(exit_price)
        position.realized_pnl = str(pnl)
        position.unrealized_pnl = "0"  # No unrealized P&L when closed
        position.closed_at = int(datetime.now(UTC).timestamp() * 1000)
        position.exit_order_id = exit_order_id

        # Add exit fee to total fees
        position.total_fees = str(position.total_fees_decimal + fee)

        # Persist changes
        position = await self._position_repo.update(position)

        logger.info(
            "position_closed",
            position_id=position_id,
            exit_price=float(exit_price),
            realized_pnl=float(pnl),
            total_fees=float(position.total_fees_decimal),
        )

        return position

    async def update_unrealized_pnl(self, position_id: str, current_price: Decimal) -> Position:
        """Update unrealized P&L for an open position.

        Args:
            position_id: Position ID to update.
            current_price: Current market price.

        Returns:
            Updated Position model.

        Raises:
            ValueError: If position not found or already closed.
        """
        position = await self._position_repo.get_by_position_id(position_id)
        if not position:
            raise ValueError(f"Position {position_id} not found")

        if position.status == "closed":
            raise ValueError(f"Position {position_id} is already closed")

        # Calculate unrealized P&L
        quantity = position.quantity_decimal
        entry_price = position.entry_price_decimal

        if position.side == "long":
            # Long: profit when price goes up
            unrealized_pnl = (current_price - entry_price) * quantity
        else:
            # Short: profit when price goes down
            unrealized_pnl = (entry_price - current_price) * quantity

        # Update position
        position.unrealized_pnl = str(unrealized_pnl)

        # Persist changes
        position = await self._position_repo.update(position)

        logger.debug(
            "position_unrealized_pnl_updated",
            position_id=position_id,
            current_price=float(current_price),
            unrealized_pnl=float(unrealized_pnl),
        )

        return position

    async def get_position(self, position_id: str) -> Position | None:
        """Get a position by ID.

        Args:
            position_id: Position ID to retrieve.

        Returns:
            Position if found, None otherwise.
        """
        return await self._position_repo.get_by_position_id(position_id)

    async def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        """Get all open positions.

        Args:
            symbol: Optional symbol filter.

        Returns:
            List of open positions.
        """
        return await self._position_repo.get_open_positions(symbol=symbol)

    async def get_total_pnl(self, symbol: str | None = None) -> dict[str, Decimal]:
        """Get total P&L across all positions.

        Args:
            symbol: Optional symbol filter.

        Returns:
            Dictionary with realized_pnl, unrealized_pnl, and total_pnl.
        """
        # Get all positions (open and closed)
        if symbol:
            open_positions = await self._position_repo.get_open_positions(symbol=symbol)
            closed_positions = await self._position_repo.get_positions_by_symbol(
                symbol=symbol, status="closed"
            )
        else:
            open_positions = await self._position_repo.get_open_positions()
            # Get all closed positions
            closed_positions = await self._position_repo.get_recent_positions(limit=1000)
            closed_positions = [p for p in closed_positions if p.status == "closed"]

        # Calculate totals
        realized_pnl = sum((p.realized_pnl_decimal for p in closed_positions), start=Decimal("0"))
        unrealized_pnl = sum((p.unrealized_pnl_decimal for p in open_positions), start=Decimal("0"))
        total_fees = sum(
            (p.total_fees_decimal for p in open_positions + closed_positions),
            start=Decimal("0"),
        )

        total_pnl = realized_pnl + unrealized_pnl - total_fees

        return {
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_fees": total_fees,
            "total_pnl": total_pnl,
        }

    async def partially_close_position(
        self,
        position_id: str,
        quantity: Decimal,
        exit_price: Decimal,
        exit_order_id: str,
        fee: Decimal = Decimal("0"),
    ) -> tuple[Position, Position]:
        """Partially close a position using FIFO accounting.

        Creates a new position for the remaining quantity and closes the
        original position for the specified quantity.

        Args:
            position_id: Position ID to partially close.
            quantity: Quantity to close.
            exit_price: Exit price.
            exit_order_id: Order ID that partially closed this position.
            fee: Exit fee.

        Returns:
            Tuple of (closed_position, remaining_position).

        Raises:
            ValueError: If position not found, already closed, or quantity invalid.
        """
        position = await self._position_repo.get_by_position_id(position_id)
        if not position:
            raise ValueError(f"Position {position_id} not found")

        if position.status == "closed":
            raise ValueError(f"Position {position_id} is already closed")

        if quantity <= 0:
            raise ValueError(f"Invalid quantity: {quantity}")

        if quantity >= position.quantity_decimal:
            raise ValueError(
                f"Quantity {quantity} must be less than position quantity {position.quantity_decimal}"
            )

        # Calculate remaining quantity before modifying position
        original_quantity = position.quantity_decimal
        remaining_quantity = original_quantity - quantity

        # Calculate realized P&L for the closed portion
        entry_price = position.entry_price_decimal

        if position.side == "long":
            pnl = (exit_price - entry_price) * quantity
        else:
            pnl = (entry_price - exit_price) * quantity

        # Split fees proportionally
        close_fee_ratio = quantity / original_quantity
        close_fees = position.total_fees_decimal * close_fee_ratio + fee
        remaining_fees = position.total_fees_decimal * (Decimal("1") - close_fee_ratio)

        # Store unrealized P&L before closing
        original_unrealized_pnl = position.unrealized_pnl_decimal

        # Update original position (close the portion)
        position.status = "closed"
        position.quantity = str(quantity)
        position.exit_price = str(exit_price)
        position.realized_pnl = str(pnl)
        position.unrealized_pnl = "0"
        position.total_fees = str(close_fees)
        position.closed_at = int(datetime.now(UTC).timestamp() * 1000)
        position.exit_order_id = exit_order_id

        position = await self._position_repo.update(position)

        # Create new position for remaining quantity
        remaining_position = await self.open_position(
            symbol=position.symbol,
            side=position.side,
            quantity=remaining_quantity,
            entry_price=entry_price,
            entry_order_id=position.entry_order_id,
            fee=remaining_fees,
            fee_currency=position.fee_currency,
            strategy_name=position.strategy_name,
            metadata={"partial_close_from": position_id} if position.position_metadata else None,
        )

        # Copy unrealized P&L to remaining position (proportional to remaining quantity)
        if original_unrealized_pnl != Decimal("0"):
            remaining_unrealized = original_unrealized_pnl * (
                remaining_quantity / original_quantity
            )
            remaining_position.unrealized_pnl = str(remaining_unrealized)
            remaining_position = await self._position_repo.update(remaining_position)

        logger.info(
            "position_partially_closed",
            position_id=position_id,
            closed_quantity=float(quantity),
            remaining_quantity=float(remaining_quantity),
            realized_pnl=float(pnl),
        )

        return position, remaining_position
