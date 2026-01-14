"""Unit tests for PositionTracker."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from cryptrink.execution.position_tracker import PositionTracker
from cryptrink.execution.repository import init_execution_db


@pytest.fixture
async def engine() -> AsyncEngine:
    """Create an in-memory SQLite engine for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_execution_db(engine)
    return engine


@pytest.fixture
async def position_tracker(engine: AsyncEngine) -> PositionTracker:
    """Create a PositionTracker instance for testing."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return PositionTracker(session_factory)


class TestPositionTracker:
    """Tests for PositionTracker class."""

    async def test_open_long_position(self, position_tracker: PositionTracker) -> None:
        """Test opening a long position."""
        position = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1.5"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
            fee=Decimal("10"),
            fee_currency="USD",
        )

        assert position.position_id.startswith("POS-")
        assert position.symbol == "BTC-USD"
        assert position.side == "long"
        assert position.status == "open"
        assert position.quantity_decimal == Decimal("1.5")
        assert position.entry_price_decimal == Decimal("50000")
        assert position.exit_price is None
        assert position.realized_pnl_decimal == Decimal("0")
        assert position.unrealized_pnl_decimal == Decimal("0")
        assert position.total_fees_decimal == Decimal("10")
        assert position.fee_currency == "USD"
        assert position.entry_order_id == "ORD-123"
        assert position.exit_order_id is None
        assert position.opened_at > 0
        assert position.closed_at is None

    async def test_open_short_position(self, position_tracker: PositionTracker) -> None:
        """Test opening a short position."""
        position = await position_tracker.open_position(
            symbol="ETH-USD",
            side="short",
            quantity=Decimal("10"),
            entry_price=Decimal("3000"),
            entry_order_id="ORD-456",
        )

        assert position.side == "short"
        assert position.quantity_decimal == Decimal("10")
        assert position.entry_price_decimal == Decimal("3000")

    async def test_close_long_position_profit(self, position_tracker: PositionTracker) -> None:
        """Test closing a long position with profit."""
        # Open position
        position = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
            fee=Decimal("5"),
        )

        # Close position at higher price (profit)
        closed_position = await position_tracker.close_position(
            position_id=position.position_id,
            exit_price=Decimal("52000"),
            exit_order_id="ORD-456",
            fee=Decimal("5"),
        )

        # Check status
        assert closed_position.status == "closed"
        assert closed_position.exit_price_decimal == Decimal("52000")
        assert closed_position.exit_order_id == "ORD-456"
        assert closed_position.closed_at is not None

        # Check P&L: (52000 - 50000) * 1 = 2000
        assert closed_position.realized_pnl_decimal == Decimal("2000")
        assert closed_position.unrealized_pnl_decimal == Decimal("0")

        # Check fees
        assert closed_position.total_fees_decimal == Decimal("10")  # 5 + 5

    async def test_close_long_position_loss(self, position_tracker: PositionTracker) -> None:
        """Test closing a long position with loss."""
        # Open position
        position = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
        )

        # Close position at lower price (loss)
        closed_position = await position_tracker.close_position(
            position_id=position.position_id,
            exit_price=Decimal("48000"),
            exit_order_id="ORD-456",
        )

        # Check P&L: (48000 - 50000) * 1 = -2000
        assert closed_position.realized_pnl_decimal == Decimal("-2000")

    async def test_close_short_position_profit(self, position_tracker: PositionTracker) -> None:
        """Test closing a short position with profit."""
        # Open position
        position = await position_tracker.open_position(
            symbol="ETH-USD",
            side="short",
            quantity=Decimal("10"),
            entry_price=Decimal("3000"),
            entry_order_id="ORD-123",
        )

        # Close position at lower price (profit for short)
        closed_position = await position_tracker.close_position(
            position_id=position.position_id,
            exit_price=Decimal("2800"),
            exit_order_id="ORD-456",
        )

        # Check P&L: (3000 - 2800) * 10 = 2000
        assert closed_position.realized_pnl_decimal == Decimal("2000")

    async def test_close_short_position_loss(self, position_tracker: PositionTracker) -> None:
        """Test closing a short position with loss."""
        # Open position
        position = await position_tracker.open_position(
            symbol="ETH-USD",
            side="short",
            quantity=Decimal("10"),
            entry_price=Decimal("3000"),
            entry_order_id="ORD-123",
        )

        # Close position at higher price (loss for short)
        closed_position = await position_tracker.close_position(
            position_id=position.position_id,
            exit_price=Decimal("3200"),
            exit_order_id="ORD-456",
        )

        # Check P&L: (3000 - 3200) * 10 = -2000
        assert closed_position.realized_pnl_decimal == Decimal("-2000")

    async def test_close_nonexistent_position_raises_error(
        self, position_tracker: PositionTracker
    ) -> None:
        """Test that closing a non-existent position raises error."""
        with pytest.raises(ValueError, match="not found"):
            await position_tracker.close_position(
                position_id="NONEXISTENT",
                exit_price=Decimal("50000"),
                exit_order_id="ORD-123",
            )

    async def test_close_already_closed_position_raises_error(
        self, position_tracker: PositionTracker
    ) -> None:
        """Test that closing an already closed position raises error."""
        # Open and close position
        position = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
        )

        await position_tracker.close_position(
            position_id=position.position_id,
            exit_price=Decimal("52000"),
            exit_order_id="ORD-456",
        )

        # Try to close again
        with pytest.raises(ValueError, match="already closed"):
            await position_tracker.close_position(
                position_id=position.position_id,
                exit_price=Decimal("53000"),
                exit_order_id="ORD-789",
            )

    async def test_update_unrealized_pnl_long_profit(
        self, position_tracker: PositionTracker
    ) -> None:
        """Test updating unrealized P&L for long position with profit."""
        # Open position
        position = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
        )

        # Update with higher price (profit)
        updated_position = await position_tracker.update_unrealized_pnl(
            position_id=position.position_id, current_price=Decimal("52000")
        )

        # Check unrealized P&L: (52000 - 50000) * 1 = 2000
        assert updated_position.unrealized_pnl_decimal == Decimal("2000")

    async def test_update_unrealized_pnl_long_loss(self, position_tracker: PositionTracker) -> None:
        """Test updating unrealized P&L for long position with loss."""
        # Open position
        position = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
        )

        # Update with lower price (loss)
        updated_position = await position_tracker.update_unrealized_pnl(
            position_id=position.position_id, current_price=Decimal("48000")
        )

        # Check unrealized P&L: (48000 - 50000) * 1 = -2000
        assert updated_position.unrealized_pnl_decimal == Decimal("-2000")

    async def test_update_unrealized_pnl_short_profit(
        self, position_tracker: PositionTracker
    ) -> None:
        """Test updating unrealized P&L for short position with profit."""
        # Open position
        position = await position_tracker.open_position(
            symbol="ETH-USD",
            side="short",
            quantity=Decimal("10"),
            entry_price=Decimal("3000"),
            entry_order_id="ORD-123",
        )

        # Update with lower price (profit for short)
        updated_position = await position_tracker.update_unrealized_pnl(
            position_id=position.position_id, current_price=Decimal("2800")
        )

        # Check unrealized P&L: (3000 - 2800) * 10 = 2000
        assert updated_position.unrealized_pnl_decimal == Decimal("2000")

    async def test_update_unrealized_pnl_short_loss(
        self, position_tracker: PositionTracker
    ) -> None:
        """Test updating unrealized P&L for short position with loss."""
        # Open position
        position = await position_tracker.open_position(
            symbol="ETH-USD",
            side="short",
            quantity=Decimal("10"),
            entry_price=Decimal("3000"),
            entry_order_id="ORD-123",
        )

        # Update with higher price (loss for short)
        updated_position = await position_tracker.update_unrealized_pnl(
            position_id=position.position_id, current_price=Decimal("3200")
        )

        # Check unrealized P&L: (3000 - 3200) * 10 = -2000
        assert updated_position.unrealized_pnl_decimal == Decimal("-2000")

    async def test_get_position(self, position_tracker: PositionTracker) -> None:
        """Test retrieving a position."""
        # Open position
        position = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
        )

        # Retrieve position
        retrieved = await position_tracker.get_position(position.position_id)

        assert retrieved is not None
        assert retrieved.position_id == position.position_id
        assert retrieved.symbol == "BTC-USD"

    async def test_get_nonexistent_position(self, position_tracker: PositionTracker) -> None:
        """Test retrieving a non-existent position returns None."""
        position = await position_tracker.get_position("NONEXISTENT")
        assert position is None

    async def test_get_open_positions(self, position_tracker: PositionTracker) -> None:
        """Test getting all open positions."""
        # Open positions
        pos1 = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
        )

        pos2 = await position_tracker.open_position(
            symbol="ETH-USD",
            side="long",
            quantity=Decimal("10"),
            entry_price=Decimal("3000"),
            entry_order_id="ORD-456",
        )

        # Close one position
        await position_tracker.close_position(
            position_id=pos1.position_id,
            exit_price=Decimal("52000"),
            exit_order_id="ORD-789",
        )

        # Get open positions
        open_positions = await position_tracker.get_open_positions()

        assert len(open_positions) == 1
        assert open_positions[0].position_id == pos2.position_id

    async def test_get_open_positions_by_symbol(self, position_tracker: PositionTracker) -> None:
        """Test getting open positions filtered by symbol."""
        await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
        )

        await position_tracker.open_position(
            symbol="ETH-USD",
            side="long",
            quantity=Decimal("10"),
            entry_price=Decimal("3000"),
            entry_order_id="ORD-456",
        )

        # Get open positions for BTC-USD
        btc_positions = await position_tracker.get_open_positions(symbol="BTC-USD")

        assert len(btc_positions) == 1
        assert btc_positions[0].symbol == "BTC-USD"

    async def test_get_total_pnl(self, position_tracker: PositionTracker) -> None:
        """Test getting total P&L across all positions."""
        # Open position 1 and close with profit
        pos1 = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
            fee=Decimal("10"),
        )
        await position_tracker.close_position(
            position_id=pos1.position_id,
            exit_price=Decimal("52000"),
            exit_order_id="ORD-456",
            fee=Decimal("10"),
        )

        # Open position 2 with unrealized profit
        pos2 = await position_tracker.open_position(
            symbol="ETH-USD",
            side="long",
            quantity=Decimal("10"),
            entry_price=Decimal("3000"),
            entry_order_id="ORD-789",
            fee=Decimal("5"),
        )
        await position_tracker.update_unrealized_pnl(
            position_id=pos2.position_id, current_price=Decimal("3100")
        )

        # Get total P&L
        total_pnl = await position_tracker.get_total_pnl()

        # Realized: 2000, Unrealized: 1000, Fees: 25, Total: 2975
        assert total_pnl["realized_pnl"] == Decimal("2000")
        assert total_pnl["unrealized_pnl"] == Decimal("1000")
        assert total_pnl["total_fees"] == Decimal("25")
        assert total_pnl["total_pnl"] == Decimal("2975")

    async def test_get_total_pnl_by_symbol(self, position_tracker: PositionTracker) -> None:
        """Test getting total P&L filtered by symbol."""
        # BTC position
        pos1 = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
            fee=Decimal("10"),
        )
        await position_tracker.close_position(
            position_id=pos1.position_id,
            exit_price=Decimal("52000"),
            exit_order_id="ORD-456",
            fee=Decimal("10"),
        )

        # ETH position
        pos2 = await position_tracker.open_position(
            symbol="ETH-USD",
            side="long",
            quantity=Decimal("10"),
            entry_price=Decimal("3000"),
            entry_order_id="ORD-789",
            fee=Decimal("5"),
        )
        await position_tracker.update_unrealized_pnl(
            position_id=pos2.position_id, current_price=Decimal("3100")
        )

        # Get total P&L for BTC only
        btc_pnl = await position_tracker.get_total_pnl(symbol="BTC-USD")

        assert btc_pnl["realized_pnl"] == Decimal("2000")
        assert btc_pnl["unrealized_pnl"] == Decimal("0")
        assert btc_pnl["total_fees"] == Decimal("20")
        assert btc_pnl["total_pnl"] == Decimal("1980")

    async def test_partially_close_position(self, position_tracker: PositionTracker) -> None:
        """Test partially closing a position."""
        # Open position
        position = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("3"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
            fee=Decimal("30"),
        )

        # Partially close 1 BTC
        closed_pos, remaining_pos = await position_tracker.partially_close_position(
            position_id=position.position_id,
            quantity=Decimal("1"),
            exit_price=Decimal("52000"),
            exit_order_id="ORD-456",
            fee=Decimal("10"),
        )

        # Check closed position
        assert closed_pos.status == "closed"
        assert closed_pos.quantity_decimal == Decimal("1")
        assert closed_pos.exit_price_decimal == Decimal("52000")
        assert closed_pos.realized_pnl_decimal == Decimal("2000")  # (52000 - 50000) * 1

        # Check remaining position
        assert remaining_pos.status == "open"
        assert remaining_pos.quantity_decimal == Decimal("2")  # 3 - 1
        assert remaining_pos.entry_price_decimal == Decimal("50000")
        assert remaining_pos.entry_order_id == "ORD-123"

    async def test_partially_close_position_invalid_quantity(
        self, position_tracker: PositionTracker
    ) -> None:
        """Test that partially closing with invalid quantity raises error."""
        # Open position
        position = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
        )

        # Try to close more than available
        with pytest.raises(ValueError, match="must be less than"):
            await position_tracker.partially_close_position(
                position_id=position.position_id,
                quantity=Decimal("2"),
                exit_price=Decimal("52000"),
                exit_order_id="ORD-456",
            )

    async def test_position_with_strategy_metadata(self, position_tracker: PositionTracker) -> None:
        """Test creating position with strategy information."""
        position = await position_tracker.open_position(
            symbol="BTC-USD",
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            entry_order_id="ORD-123",
            strategy_name="sma_crossover",
            metadata={"signal_strength": "strong", "sma_fast": 10},
        )

        assert position.strategy_name == "sma_crossover"
        assert position.position_metadata is not None
