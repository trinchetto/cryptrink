"""Unit tests for SuggestExecutor."""

from datetime import UTC, datetime
from decimal import Decimal

from cryptrink.execution.base import (
    ExecutionContext,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    OrderType,
)
from cryptrink.execution.suggest import SuggestExecutor
from cryptrink.strategies.base import Signal, SignalStrength, SignalType


class TestSuggestExecutor:
    """Tests for SuggestExecutor class."""

    async def test_initialization(self) -> None:
        """Test that SuggestExecutor initializes correctly."""
        executor = SuggestExecutor()

        assert executor.mode == ExecutionMode.SUGGEST
        assert executor._suggestion_counter == 0

    async def test_hold_signal_ignored(self) -> None:
        """Test that HOLD signals are ignored."""
        executor = SuggestExecutor()
        signal = Signal(
            signal_type=SignalType.HOLD,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.MODERATE,
        )
        context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=Decimal("10000"),
            has_position=False,
        )

        result = await executor.execute_signal(signal, context)

        assert result.success is False
        assert "HOLD" in result.message
        assert result.metadata["signal_type"] == "hold"

    async def test_entry_long_generates_buy_suggestion(self) -> None:
        """Test that ENTRY_LONG signal generates a BUY suggestion."""
        executor = SuggestExecutor()
        signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.MODERATE,
        )
        context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=Decimal("10000"),
            has_position=False,
        )

        result = await executor.execute_signal(signal, context)

        assert result.success is True
        assert result.order_id is not None
        assert result.order_id.startswith("SUGGEST-")
        assert result.order_type == OrderType.MARKET
        assert result.order_side == OrderSide.BUY
        assert result.quantity is not None
        assert result.quantity > 0
        assert result.price == Decimal("50000")
        assert result.status == OrderStatus.PENDING
        assert result.metadata["suggestion_only"] is True
        assert result.metadata["signal_type"] == "entry_long"
        assert result.metadata["signal_strength"] == "moderate"

    async def test_exit_long_generates_sell_suggestion(self) -> None:
        """Test that EXIT_LONG signal generates a SELL suggestion."""
        executor = SuggestExecutor()
        signal = Signal(
            signal_type=SignalType.EXIT_LONG,
            symbol="ETH-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("3000"),
            strength=SignalStrength.STRONG,
        )
        context = ExecutionContext(
            symbol="ETH-USD",
            current_price=Decimal("3000"),
            timestamp=datetime.now(UTC),
            account_balance=Decimal("10000"),
            has_position=True,
            position_size=Decimal("5"),
        )

        result = await executor.execute_signal(signal, context)

        assert result.success is True
        assert result.order_side == OrderSide.SELL
        assert result.metadata["signal_type"] == "exit_long"
        assert result.metadata["signal_strength"] == "strong"

    async def test_suggestion_counter_increments(self) -> None:
        """Test that suggestion counter increments for each suggestion."""
        executor = SuggestExecutor()
        signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.MODERATE,
        )
        context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=Decimal("10000"),
            has_position=False,
        )

        result1 = await executor.execute_signal(signal, context)
        result2 = await executor.execute_signal(signal, context)
        result3 = await executor.execute_signal(signal, context)

        assert result1.order_id == "SUGGEST-000001"
        assert result2.order_id == "SUGGEST-000002"
        assert result3.order_id == "SUGGEST-000003"

    async def test_quantity_calculation(self) -> None:
        """Test that quantity is calculated as 10% of available balance."""
        executor = SuggestExecutor()
        signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.MODERATE,
        )
        context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=Decimal("10000"),
            has_position=False,
        )

        result = await executor.execute_signal(signal, context)

        # 10% of 10000 = 1000, divided by price 50000 = 0.02
        expected_quantity = Decimal("0.02")
        assert result.quantity == expected_quantity

    async def test_stop_loss_and_take_profit_in_metadata(self) -> None:
        """Test that stop loss and take profit are included in metadata."""
        executor = SuggestExecutor()
        signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.MODERATE,
            stop_loss=Decimal("48000"),
            take_profit=Decimal("55000"),
        )
        context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=Decimal("10000"),
            has_position=False,
        )

        result = await executor.execute_signal(signal, context)

        assert result.metadata["stop_loss"] == 48000.0
        assert result.metadata["take_profit"] == 55000.0

    async def test_cancel_order_returns_false(self) -> None:
        """Test that cancel_order returns False for suggestions."""
        executor = SuggestExecutor()

        result = await executor.cancel_order("SUGGEST-000001")

        assert result is False

    async def test_get_order_status_returns_pending(self) -> None:
        """Test that get_order_status always returns PENDING."""
        executor = SuggestExecutor()

        status = await executor.get_order_status("SUGGEST-000001")

        assert status == OrderStatus.PENDING

    async def test_sync_state_noop(self) -> None:
        """Test that sync_state is a no-op."""
        executor = SuggestExecutor()

        # Should not raise any errors
        await executor.sync_state()

    async def test_repr(self) -> None:
        """Test string representation."""
        executor = SuggestExecutor()

        repr_str = repr(executor)

        assert "SuggestExecutor" in repr_str
        assert "suggest" in repr_str
