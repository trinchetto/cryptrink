"""Unit tests for PaperExecutor."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cryptrink.execution.base import (
    ExecutionContext,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    OrderType,
)
from cryptrink.execution.paper import PaperExecutor
from cryptrink.strategies.base import Signal, SignalStrength, SignalType


class TestPaperExecutor:
    """Tests for PaperExecutor class."""

    async def test_initialization_default_balance(self) -> None:
        """Test that PaperExecutor initializes with default balance."""
        executor = PaperExecutor()

        assert executor.mode == ExecutionMode.PAPER
        assert executor.balance == Decimal("10000")
        assert executor.initial_balance == Decimal("10000")

    async def test_initialization_custom_balance(self) -> None:
        """Test that PaperExecutor initializes with custom balance."""
        executor = PaperExecutor(initial_balance=Decimal("50000"))

        assert executor.balance == Decimal("50000")
        assert executor.initial_balance == Decimal("50000")

    async def test_hold_signal_ignored(self) -> None:
        """Test that HOLD signals are ignored."""
        executor = PaperExecutor()
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

    async def test_buy_order_execution(self) -> None:
        """Test executing a BUY order in paper mode."""
        executor = PaperExecutor(initial_balance=Decimal("10000"))
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
            account_balance=executor.balance,
            has_position=False,
        )

        result = await executor.execute_signal(signal, context)

        assert result.success is True
        assert result.order_id is not None
        assert result.order_id.startswith("PAPER-")
        assert result.order_type == OrderType.MARKET
        assert result.order_side == OrderSide.BUY
        assert result.status == OrderStatus.FILLED
        assert result.quantity is not None
        assert result.quantity > 0

        # Balance should decrease
        assert executor.balance < Decimal("10000")

        # Should have a position
        position = executor.get_position("BTC-USD")
        assert position is not None
        assert position["quantity"] == result.quantity
        assert position["entry_price"] == Decimal("50000")

    async def test_sell_order_execution(self) -> None:
        """Test executing a SELL order in paper mode."""
        executor = PaperExecutor(initial_balance=Decimal("10000"))

        # First buy to create a position
        buy_signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.MODERATE,
        )
        buy_context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=executor.balance,
            has_position=False,
        )
        buy_result = await executor.execute_signal(buy_signal, buy_context)
        bought_quantity = buy_result.quantity

        balance_after_buy = executor.balance

        # Now sell
        sell_signal = Signal(
            signal_type=SignalType.EXIT_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("52000"),
            strength=SignalStrength.MODERATE,
        )
        sell_context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("52000"),
            timestamp=datetime.now(UTC),
            account_balance=executor.balance,
            has_position=True,
            position_size=bought_quantity,  # type: ignore[arg-type]
        )
        sell_result = await executor.execute_signal(sell_signal, sell_context)

        assert sell_result.success is True
        assert sell_result.order_side == OrderSide.SELL
        assert sell_result.status == OrderStatus.FILLED
        assert sell_result.quantity == bought_quantity

        # Balance should increase (profit from price increase)
        assert executor.balance > balance_after_buy

        # Position should be closed
        position = executor.get_position("BTC-USD")
        assert position is None

    async def test_insufficient_balance_rejection(self) -> None:
        """Test that orders are rejected with insufficient balance."""
        # First, execute a trade that uses most of the balance
        executor = PaperExecutor(initial_balance=Decimal("1000"))

        # Buy to use up 90% of balance (10% allocation)
        first_signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.MODERATE,
        )
        first_context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=executor.balance,
            has_position=False,
        )
        await executor.execute_signal(first_signal, first_context)

        # Manually set balance to very low amount
        executor._balance = Decimal("0.0001")

        # Now try to buy again with insufficient balance
        signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="ETH-USD",  # Different symbol
            timestamp=datetime.now(UTC),
            price=Decimal("3000"),
            strength=SignalStrength.MODERATE,
        )
        context = ExecutionContext(
            symbol="ETH-USD",
            current_price=Decimal("3000"),
            timestamp=datetime.now(UTC),
            account_balance=executor.balance,
            has_position=False,
        )

        result = await executor.execute_signal(signal, context)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        # Either "Invalid quantity" (quantity rounds to 0) or "Insufficient balance"
        assert "Invalid quantity" in result.message or "Insufficient balance" in result.message

    async def test_sell_without_position_rejection(self) -> None:
        """Test that sell orders are rejected without a position."""
        executor = PaperExecutor()
        signal = Signal(
            signal_type=SignalType.EXIT_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.MODERATE,
        )
        context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=executor.balance,
            has_position=False,
        )

        result = await executor.execute_signal(signal, context)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        # Either "No position" or "Invalid quantity" (quantity is 0 without position)
        assert "No position" in result.message or "Invalid quantity" in result.message

    async def test_cancel_filled_order_fails(self) -> None:
        """Test that filled orders cannot be cancelled."""
        executor = PaperExecutor()
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
            account_balance=executor.balance,
            has_position=False,
        )

        result = await executor.execute_signal(signal, context)
        order_id = result.order_id

        cancel_result = await executor.cancel_order(order_id)  # type: ignore[arg-type]

        assert cancel_result is False

    async def test_get_order_status(self) -> None:
        """Test getting order status."""
        executor = PaperExecutor()
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
            account_balance=executor.balance,
            has_position=False,
        )

        result = await executor.execute_signal(signal, context)
        order_id = result.order_id

        status = await executor.get_order_status(order_id)  # type: ignore[arg-type]

        assert status == OrderStatus.FILLED

    async def test_get_order_status_not_found(self) -> None:
        """Test that KeyError is raised for unknown order ID."""
        executor = PaperExecutor()

        with pytest.raises(KeyError, match="not found"):
            await executor.get_order_status("INVALID-ORDER-ID")

    async def test_reset_clears_state(self) -> None:
        """Test that reset clears all state."""
        executor = PaperExecutor(initial_balance=Decimal("10000"))

        # Execute some trades
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
            account_balance=executor.balance,
            has_position=False,
        )
        await executor.execute_signal(signal, context)

        # Reset
        executor.reset()

        assert executor.balance == Decimal("10000")
        assert len(executor._orders) == 0
        assert len(executor._positions) == 0

    async def test_reset_with_new_balance(self) -> None:
        """Test that reset can change the initial balance."""
        executor = PaperExecutor(initial_balance=Decimal("10000"))

        executor.reset(initial_balance=Decimal("20000"))

        assert executor.balance == Decimal("20000")
        assert executor.initial_balance == Decimal("20000")

    async def test_sync_state_noop(self) -> None:
        """Test that sync_state is a no-op."""
        executor = PaperExecutor()

        # Should not raise any errors
        await executor.sync_state()

    async def test_average_entry_price_multiple_buys(self) -> None:
        """Test that average entry price is calculated correctly with multiple buys."""
        executor = PaperExecutor(initial_balance=Decimal("100000"))

        # First buy
        signal1 = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.MODERATE,
        )
        context1 = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=executor.balance,
            has_position=False,
        )
        result1 = await executor.execute_signal(signal1, context1)
        quantity1 = result1.quantity

        # Second buy at different price
        signal2 = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("52000"),
            strength=SignalStrength.MODERATE,
        )
        context2 = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("52000"),
            timestamp=datetime.now(UTC),
            account_balance=executor.balance,
            has_position=True,
            position_size=quantity1,  # type: ignore[arg-type]
        )
        result2 = await executor.execute_signal(signal2, context2)
        quantity2 = result2.quantity

        # Check average entry price
        position = executor.get_position("BTC-USD")
        assert position is not None

        expected_avg_price = (
            Decimal("50000") * quantity1 + Decimal("52000") * quantity2  # type: ignore[operator]
        ) / (quantity1 + quantity2)  # type: ignore[operator]

        assert position["entry_price"] == expected_avg_price
        assert position["quantity"] == quantity1 + quantity2  # type: ignore[operator]
