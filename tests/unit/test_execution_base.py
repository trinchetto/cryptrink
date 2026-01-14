"""Unit tests for execution base classes and enums."""

from datetime import UTC, datetime
from decimal import Decimal

from cryptrink.execution.base import (
    ExecutionContext,
    ExecutionMode,
    ExecutionResult,
    OrderSide,
    OrderStatus,
    OrderType,
)


class TestEnums:
    """Tests for execution enums."""

    def test_execution_mode_values(self) -> None:
        """Test that ExecutionMode has expected values."""
        assert ExecutionMode.LIVE.value == "live"
        assert ExecutionMode.PAPER.value == "paper"
        assert ExecutionMode.SUGGEST.value == "suggest"
        assert ExecutionMode.BACKTEST.value == "backtest"

    def test_order_type_values(self) -> None:
        """Test that OrderType has expected values."""
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"

    def test_order_side_values(self) -> None:
        """Test that OrderSide has expected values."""
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_status_values(self) -> None:
        """Test that OrderStatus has expected values."""
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.SUBMITTED.value == "submitted"
        assert OrderStatus.PARTIALLY_FILLED.value == "partially_filled"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"
        assert OrderStatus.EXPIRED.value == "expired"


class TestExecutionContext:
    """Tests for ExecutionContext dataclass."""

    def test_minimal_initialization(self) -> None:
        """Test creating ExecutionContext with minimal required fields."""
        context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=Decimal("10000"),
            has_position=False,
        )

        assert context.symbol == "BTC-USD"
        assert context.current_price == Decimal("50000")
        assert context.account_balance == Decimal("10000")
        assert context.has_position is False
        assert context.position_size == Decimal("0")
        assert context.position_entry_price is None
        # available_balance should default to account_balance
        assert context.available_balance == Decimal("10000")

    def test_full_initialization(self) -> None:
        """Test creating ExecutionContext with all fields."""
        timestamp = datetime.now(UTC)
        context = ExecutionContext(
            symbol="ETH-USD",
            current_price=Decimal("3000"),
            timestamp=timestamp,
            account_balance=Decimal("20000"),
            has_position=True,
            position_size=Decimal("5"),
            position_entry_price=Decimal("2900"),
            available_balance=Decimal("15000"),
            metadata={"test": "value"},
        )

        assert context.symbol == "ETH-USD"
        assert context.current_price == Decimal("3000")
        assert context.timestamp == timestamp
        assert context.account_balance == Decimal("20000")
        assert context.has_position is True
        assert context.position_size == Decimal("5")
        assert context.position_entry_price == Decimal("2900")
        assert context.available_balance == Decimal("15000")
        assert context.metadata == {"test": "value"}

    def test_timestamp_timezone_added(self) -> None:
        """Test that timezone is added to timestamp if missing."""
        naive_time = datetime(2025, 1, 15, 12, 0, 0)
        context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=naive_time,
            account_balance=Decimal("10000"),
            has_position=False,
        )

        assert context.timestamp.tzinfo == UTC

    def test_available_balance_defaults_to_account_balance(self) -> None:
        """Test that available_balance defaults to account_balance when zero."""
        context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=Decimal("10000"),
            has_position=False,
        )

        assert context.available_balance == context.account_balance


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_minimal_successful_result(self) -> None:
        """Test creating a minimal successful ExecutionResult."""
        result = ExecutionResult(success=True)

        assert result.success is True
        assert result.order_id is None
        assert result.order_type is None
        assert result.order_side is None
        assert result.quantity is None
        assert result.price is None
        assert result.status == OrderStatus.PENDING
        assert result.message == ""
        assert result.error is None
        assert isinstance(result.timestamp, datetime)
        assert result.timestamp.tzinfo == UTC

    def test_full_successful_result(self) -> None:
        """Test creating a complete successful ExecutionResult."""
        timestamp = datetime.now(UTC)
        result = ExecutionResult(
            success=True,
            order_id="ORDER123",
            order_type=OrderType.MARKET,
            order_side=OrderSide.BUY,
            quantity=Decimal("1.5"),
            price=Decimal("50000"),
            status=OrderStatus.FILLED,
            timestamp=timestamp,
            message="Order filled successfully",
            metadata={"exchange": "revolut_x"},
        )

        assert result.success is True
        assert result.order_id == "ORDER123"
        assert result.order_type == OrderType.MARKET
        assert result.order_side == OrderSide.BUY
        assert result.quantity == Decimal("1.5")
        assert result.price == Decimal("50000")
        assert result.status == OrderStatus.FILLED
        assert result.timestamp == timestamp
        assert result.message == "Order filled successfully"
        assert result.error is None
        assert result.metadata == {"exchange": "revolut_x"}

    def test_failed_result_with_error(self) -> None:
        """Test creating a failed ExecutionResult with error."""
        result = ExecutionResult(
            success=False,
            status=OrderStatus.REJECTED,
            message="Insufficient balance",
            error="Insufficient balance",
            metadata={"reason": "balance_too_low"},
        )

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert result.message == "Insufficient balance"
        assert result.error == "Insufficient balance"
        assert result.metadata == {"reason": "balance_too_low"}

    def test_timestamp_timezone_added(self) -> None:
        """Test that timezone is added to timestamp if missing."""
        naive_time = datetime(2025, 1, 15, 12, 0, 0)
        result = ExecutionResult(
            success=True,
            timestamp=naive_time,
        )

        assert result.timestamp.tzinfo == UTC

    def test_timestamp_defaults_to_now(self) -> None:
        """Test that timestamp defaults to current time."""
        before = datetime.now(UTC)
        result = ExecutionResult(success=True)
        after = datetime.now(UTC)

        assert before <= result.timestamp <= after
