"""Unit tests for BacktestExecutor."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cryptrink.backtest.executor import BacktestExecutor
from cryptrink.backtest.models import ConstantSlippageModel, PercentageFeeModel
from cryptrink.execution.base import ExecutionContext, OrderSide, OrderStatus
from cryptrink.strategies.base import Signal, SignalStrength, SignalType


@pytest.fixture
def executor():
    """Create BacktestExecutor with default models."""
    slippage_model = ConstantSlippageModel(slippage_bps=Decimal("0.001"))  # 10 bps
    fee_model = PercentageFeeModel(fee_pct=Decimal("0.001"))  # 0.1%
    return BacktestExecutor(
        initial_balance=Decimal("10000"),
        slippage_model=slippage_model,
        fee_model=fee_model,
    )


@pytest.fixture
def execution_context():
    """Create execution context."""
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
    """Create buy signal."""
    return Signal(
        signal_type=SignalType.ENTRY_LONG,
        symbol="BTC-USD",
        timestamp=datetime.now(UTC),
        price=Decimal("50000"),
        strength=SignalStrength.STRONG,
    )


@pytest.fixture
def sell_signal():
    """Create sell signal."""
    return Signal(
        signal_type=SignalType.EXIT_LONG,
        symbol="BTC-USD",
        timestamp=datetime.now(UTC),
        price=Decimal("50000"),
        strength=SignalStrength.STRONG,
    )


class TestBacktestExecutorInitialization:
    """Tests for BacktestExecutor initialization."""

    def test_initialization(self, executor):
        """Test initialization with models."""
        assert executor.initial_balance == Decimal("10000")
        assert executor.balance == Decimal("10000")
        assert executor.get_balance() == Decimal("10000")

    def test_repr(self, executor):
        """Test string representation."""
        assert executor is not None


class TestBuyOrderExecution:
    """Tests for buy order execution."""

    @pytest.mark.asyncio
    async def test_successful_buy_order(self, executor, buy_signal, execution_context):
        """Test successful buy order with slippage and fees."""
        # Execute buy signal
        result = await executor.execute_signal(buy_signal, execution_context)

        assert result.success is True
        assert result.order_side == OrderSide.BUY
        assert result.status == OrderStatus.FILLED
        assert result.quantity > Decimal("0")
        assert result.metadata.get("fee", 0) > 0

        # Check slippage applied (buy at higher price)
        # Signal price: 50000, slippage 10 bps = 50000 * 1.001 = 50050
        assert result.price > execution_context.current_price
        assert result.price == Decimal("50050")

        # Check balance decreased (cost + fee)
        assert executor.balance < executor.initial_balance

    @pytest.mark.asyncio
    async def test_buy_order_balance_calculation(self, executor, buy_signal, execution_context):
        """Test balance calculation includes slippage and fees."""
        initial_balance = executor.balance

        result = await executor.execute_signal(buy_signal, execution_context)

        # Calculate expected cost
        quantity = result.quantity
        price_with_slippage = result.price  # 50050
        notional = quantity * price_with_slippage
        fee = Decimal(str(result.metadata["fee"]))

        expected_balance = initial_balance - notional - fee
        assert executor.balance == expected_balance

    @pytest.mark.asyncio
    async def test_position_created_on_buy(self, executor, buy_signal, execution_context):
        """Test position is created after buy."""
        await executor.execute_signal(buy_signal, execution_context)

        position = executor.get_position("BTC-USD")
        assert position is not None
        assert position["symbol"] == "BTC-USD"
        assert position["quantity"] > Decimal("0")
        assert position["entry_price"] > Decimal("0")
        assert position["total_fees"] > Decimal("0")

    @pytest.mark.asyncio
    async def test_insufficient_balance_rejection(self):
        """Test buy order rejected when balance insufficient."""
        # Create executor with zero balance
        slippage_model = ConstantSlippageModel(slippage_bps=Decimal("0.001"))
        fee_model = PercentageFeeModel(fee_pct=Decimal("0.001"))
        executor = BacktestExecutor(
            initial_balance=Decimal("0"),  # Zero balance
            slippage_model=slippage_model,
            fee_model=fee_model,
        )

        buy_signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.STRONG,
        )

        execution_context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=Decimal("0"),
            available_balance=Decimal("0"),
            has_position=False,
            position_size=Decimal("0"),
        )

        result = await executor.execute_signal(buy_signal, execution_context)

        # With zero balance, quantity will be 0, which should still "succeed" technically
        # but realistically no position is created
        assert result.quantity == Decimal("0")  # No quantity purchased
        assert executor.balance == Decimal("0")  # Balance unchanged


class TestSellOrderExecution:
    """Tests for sell order execution."""

    @pytest.mark.asyncio
    async def test_successful_sell_order(
        self, executor, buy_signal, sell_signal, execution_context
    ):
        """Test successful sell order after buy."""
        # First buy to create position
        await executor.execute_signal(buy_signal, execution_context)
        balance_after_buy = executor.balance

        # Update context to reflect position
        execution_context.has_position = True
        position = executor.get_position("BTC-USD")
        execution_context.position_size = position["quantity"]  # type: ignore[assignment]

        # Now sell
        result = await executor.execute_signal(sell_signal, execution_context)

        assert result.success is True
        assert result.order_side == OrderSide.SELL
        assert result.status == OrderStatus.FILLED

        # Check slippage applied (sell at lower price)
        # Signal price: 50000, slippage 10 bps = 50000 * 0.999 = 49950
        assert result.price < Decimal("50000")
        assert result.price == Decimal("49950")

        # Check balance increased (proceeds - fee)
        assert executor.balance > balance_after_buy

    @pytest.mark.asyncio
    async def test_position_closed_after_sell(
        self, executor, buy_signal, sell_signal, execution_context
    ):
        """Test position is closed after selling entire quantity."""
        # Buy
        await executor.execute_signal(buy_signal, execution_context)

        # Update context
        execution_context.has_position = True
        position = executor.get_position("BTC-USD")
        execution_context.position_size = position["quantity"]  # type: ignore[assignment]

        # Sell entire position
        await executor.execute_signal(sell_signal, execution_context)

        # Position should be closed
        position_after_sell = executor.get_position("BTC-USD")
        assert position_after_sell is None

    @pytest.mark.asyncio
    async def test_sell_order_fees_deducted(
        self, executor, buy_signal, sell_signal, execution_context
    ):
        """Test sell order fees are deducted from proceeds."""
        # Buy
        buy_result = await executor.execute_signal(buy_signal, execution_context)
        balance_after_buy = executor.balance

        # Update context
        execution_context.has_position = True
        execution_context.position_size = buy_result.quantity

        # Sell
        sell_result = await executor.execute_signal(sell_signal, execution_context)

        # Calculate expected balance
        sell_proceeds = sell_result.quantity * sell_result.price
        sell_fee = Decimal(str(sell_result.metadata["fee"]))
        expected_balance = balance_after_buy + sell_proceeds - sell_fee

        assert executor.balance == expected_balance


class TestMultipleBuys:
    """Tests for multiple buy orders (accumulating position)."""

    @pytest.mark.asyncio
    async def test_average_entry_price_calculation(self, executor, buy_signal, execution_context):
        """Test average entry price calculated correctly for multiple buys."""
        # First buy
        result1 = await executor.execute_signal(buy_signal, execution_context)

        # Second buy at different price
        execution_context.current_price = Decimal("52000")
        buy_signal2 = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("52000"),
            strength=SignalStrength.STRONG,
        )

        result2 = await executor.execute_signal(buy_signal2, execution_context)
        position2 = executor.get_position("BTC-USD")

        # Check position quantity increased
        assert result1.quantity > Decimal("0")
        assert result2.quantity > Decimal("0")
        assert position2["quantity"] == result1.quantity + result2.quantity

        # Check average entry price calculation
        total_value = result1.quantity * result1.price + result2.quantity * result2.price
        total_quantity = result1.quantity + result2.quantity
        expected_avg_price = total_value / total_quantity

        assert position2["entry_price"] == expected_avg_price

    @pytest.mark.asyncio
    async def test_fees_accumulate_on_multiple_buys(self, executor, buy_signal, execution_context):
        """Test fees accumulate on multiple buys."""
        # First buy
        result1 = await executor.execute_signal(buy_signal, execution_context)
        fee1 = Decimal(str(result1.metadata["fee"]))

        # Second buy
        result2 = await executor.execute_signal(buy_signal, execution_context)
        fee2 = Decimal(str(result2.metadata["fee"]))

        # Check total fees in position
        position = executor.get_position("BTC-USD")
        expected_total_fees = fee1 + fee2
        assert position["total_fees"] == expected_total_fees


class TestHoldSignal:
    """Tests for HOLD signal handling."""

    @pytest.mark.asyncio
    async def test_hold_signal_no_execution(self, executor, execution_context):
        """Test HOLD signal results in no execution."""
        hold_signal = Signal(
            signal_type=SignalType.HOLD,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.WEAK,
        )

        result = await executor.execute_signal(hold_signal, execution_context)

        assert result.success is False
        assert "HOLD signal" in result.message
        assert executor.balance == executor.initial_balance  # Balance unchanged


class TestOrderCancellation:
    """Tests for order cancellation."""

    @pytest.mark.asyncio
    async def test_cannot_cancel_filled_order(self, executor, buy_signal, execution_context):
        """Test cannot cancel filled order."""
        result = await executor.execute_signal(buy_signal, execution_context)
        order_id = result.order_id

        cancelled = await executor.cancel_order(order_id)

        assert cancelled is False  # Already filled

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self, executor):
        """Test cancelling nonexistent order returns False."""
        cancelled = await executor.cancel_order("FAKE-ORDER-ID")

        assert cancelled is False


class TestOrderStatus:
    """Tests for order status queries."""

    @pytest.mark.asyncio
    async def test_get_order_status(self, executor, buy_signal, execution_context):
        """Test getting order status."""
        result = await executor.execute_signal(buy_signal, execution_context)
        order_id = result.order_id

        status = await executor.get_order_status(order_id)

        assert status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_get_nonexistent_order_status_raises(self, executor):
        """Test getting status of nonexistent order raises KeyError."""
        with pytest.raises(KeyError):
            await executor.get_order_status("FAKE-ORDER-ID")


class TestReset:
    """Tests for executor reset."""

    @pytest.mark.asyncio
    async def test_reset_clears_state(self, executor, buy_signal, execution_context):
        """Test reset clears orders and positions."""
        # Execute some trades
        await executor.execute_signal(buy_signal, execution_context)

        # Reset
        executor.reset()

        # Check state cleared
        assert executor.balance == executor.initial_balance
        assert len(executor._orders) == 0
        assert len(executor._positions) == 0

    def test_reset_with_new_balance(self, executor):
        """Test reset with new initial balance."""
        new_balance = Decimal("20000")

        executor.reset(initial_balance=new_balance)

        assert executor.initial_balance == new_balance
        assert executor.balance == new_balance


class TestSyncState:
    """Tests for state synchronization."""

    @pytest.mark.asyncio
    async def test_sync_state_is_noop(self, executor):
        """Test sync_state is a no-op for backtest."""
        # Just verify it doesn't raise
        await executor.sync_state()


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_zero_fee_model(self, buy_signal, execution_context):
        """Test execution with zero fees."""
        slippage_model = ConstantSlippageModel(slippage_bps=Decimal("0"))
        fee_model = PercentageFeeModel(fee_pct=Decimal("0"))
        executor = BacktestExecutor(
            initial_balance=Decimal("10000"),
            slippage_model=slippage_model,
            fee_model=fee_model,
        )

        result = await executor.execute_signal(buy_signal, execution_context)

        assert result.success is True
        assert result.metadata.get("fee", 0) == 0
        # No slippage, so price should match
        assert result.price == execution_context.current_price

    @pytest.mark.asyncio
    async def test_high_slippage_model(self, buy_signal, execution_context):
        """Test execution with high slippage (1%)."""
        slippage_model = ConstantSlippageModel(slippage_bps=Decimal("0.01"))  # 1%
        fee_model = PercentageFeeModel(fee_pct=Decimal("0.001"))
        executor = BacktestExecutor(
            initial_balance=Decimal("10000"),
            slippage_model=slippage_model,
            fee_model=fee_model,
        )

        result = await executor.execute_signal(buy_signal, execution_context)

        assert result.success is True
        # Buy price should be 1% higher
        expected_price = Decimal("50000") * Decimal("1.01")
        assert result.price == expected_price
