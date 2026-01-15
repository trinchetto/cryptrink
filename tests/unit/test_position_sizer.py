"""Unit tests for PositionSizer."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cryptrink.execution.base import ExecutionContext, OrderSide
from cryptrink.risk.position_sizer import PositionSizer, SizingStrategy
from cryptrink.strategies.base import Signal, SignalStrength, SignalType


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
    """Create a sample buy signal with stop-loss."""
    return Signal(
        signal_type=SignalType.ENTRY_LONG,
        symbol="BTC-USD",
        timestamp=datetime.now(UTC),
        price=Decimal("50000"),
        strength=SignalStrength.STRONG,
        stop_loss=Decimal("49000"),  # 2% stop-loss
    )


@pytest.fixture
def buy_signal_no_stop():
    """Create a buy signal without stop-loss."""
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


class TestPositionSizerInitialization:
    """Tests for PositionSizer initialization."""

    def test_default_initialization(self):
        """Test default initialization with Fixed Fractional strategy."""
        sizer = PositionSizer()

        assert sizer.strategy == SizingStrategy.FIXED_FRACTIONAL
        assert sizer.risk_per_trade == Decimal("0.02")
        assert sizer._kelly_fraction == Decimal("0.25")
        assert sizer._volatility_multiplier == Decimal("2.0")
        assert sizer._default_stop_loss_pct == Decimal("0.02")

    def test_custom_initialization(self):
        """Test initialization with custom parameters."""
        sizer = PositionSizer(
            strategy=SizingStrategy.VOLATILITY_BASED,
            risk_per_trade=Decimal("0.03"),
            kelly_fraction=Decimal("0.5"),
            volatility_multiplier=Decimal("3.0"),
            default_stop_loss_pct=Decimal("0.03"),
        )

        assert sizer.strategy == SizingStrategy.VOLATILITY_BASED
        assert sizer.risk_per_trade == Decimal("0.03")
        assert sizer._kelly_fraction == Decimal("0.5")
        assert sizer._volatility_multiplier == Decimal("3.0")
        assert sizer._default_stop_loss_pct == Decimal("0.03")

    def test_repr(self):
        """Test string representation."""
        sizer = PositionSizer()
        repr_str = repr(sizer)

        assert "PositionSizer" in repr_str
        assert "fixed_fractional" in repr_str
        assert "0.02" in repr_str


class TestFixedFractionalSizing:
    """Tests for Fixed Fractional position sizing."""

    def test_fixed_fractional_with_stop_loss(self, execution_context, buy_signal):
        """Test fixed fractional sizing with stop-loss specified."""
        sizer = PositionSizer(
            strategy=SizingStrategy.FIXED_FRACTIONAL,
            risk_per_trade=Decimal("0.02"),
        )

        quantity = sizer.calculate_position_size(execution_context, buy_signal, OrderSide.BUY)

        # Risk amount = 10000 * 0.02 = 200
        # Risk per unit = 50000 - 49000 = 1000
        # Position size = 200 / 1000 = 0.2 BTC
        assert quantity == Decimal("0.2")

    def test_fixed_fractional_without_stop_loss(self, execution_context, buy_signal_no_stop):
        """Test fixed fractional sizing when stop-loss not specified."""
        sizer = PositionSizer(
            strategy=SizingStrategy.FIXED_FRACTIONAL,
            risk_per_trade=Decimal("0.02"),
            default_stop_loss_pct=Decimal("0.02"),
        )

        quantity = sizer.calculate_position_size(
            execution_context, buy_signal_no_stop, OrderSide.BUY
        )

        # Default stop-loss = 50000 * (1 - 0.02) = 49000
        # Risk per unit = 50000 - 49000 = 1000
        # Risk amount = 10000 * 0.02 = 200
        # Position size = 200 / 1000 = 0.2 BTC
        assert quantity == Decimal("0.2")

    def test_fixed_fractional_different_risk_pct(self, execution_context, buy_signal):
        """Test fixed fractional with different risk percentage."""
        sizer = PositionSizer(
            strategy=SizingStrategy.FIXED_FRACTIONAL,
            risk_per_trade=Decimal("0.01"),  # 1% risk
        )

        quantity = sizer.calculate_position_size(execution_context, buy_signal, OrderSide.BUY)

        # Risk amount = 10000 * 0.01 = 100
        # Risk per unit = 1000
        # Position size = 100 / 1000 = 0.1 BTC
        assert quantity == Decimal("0.1")

    def test_fixed_fractional_tight_stop_loss(self, execution_context):
        """Test with tight stop-loss (larger position)."""
        # Stop-loss at 0.5% instead of 2%
        signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.STRONG,
            stop_loss=Decimal("49750"),  # 0.5% stop-loss
        )

        sizer = PositionSizer(
            strategy=SizingStrategy.FIXED_FRACTIONAL,
            risk_per_trade=Decimal("0.02"),
        )

        quantity = sizer.calculate_position_size(execution_context, signal, OrderSide.BUY)

        # Risk per unit = 50000 - 49750 = 250
        # Risk amount = 10000 * 0.02 = 200
        # Position size = 200 / 250 = 0.8 BTC
        assert quantity == Decimal("0.8")

    def test_fixed_fractional_zero_risk_fallback(self, execution_context):
        """Test fallback when risk per unit is zero."""
        # Stop-loss equals entry price (edge case)
        signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.STRONG,
            stop_loss=Decimal("50000"),  # Same as entry
        )

        sizer = PositionSizer(strategy=SizingStrategy.FIXED_FRACTIONAL)

        quantity = sizer.calculate_position_size(execution_context, signal, OrderSide.BUY)

        # Should fallback to simple 10% allocation
        # 10000 * 0.1 / 50000 = 0.02 BTC
        assert quantity == Decimal("0.02")


class TestVolatilityBasedSizing:
    """Tests for Volatility-Based position sizing."""

    def test_volatility_based_with_atr(self, execution_context):
        """Test volatility-based sizing with ATR in signal."""
        signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.STRONG,
            metadata={"atr": 1000},  # ATR = $1000
        )

        sizer = PositionSizer(
            strategy=SizingStrategy.VOLATILITY_BASED,
            risk_per_trade=Decimal("0.02"),
            volatility_multiplier=Decimal("2.0"),
        )

        quantity = sizer.calculate_position_size(execution_context, signal, OrderSide.BUY)

        # Risk amount = 10000 * 0.02 = 200
        # Volatility risk = 1000 * 2.0 = 2000
        # Position size = 200 / 2000 = 0.1 BTC
        assert quantity == Decimal("0.1")

    def test_volatility_based_high_volatility(self, execution_context):
        """Test that high volatility results in smaller position."""
        signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.STRONG,
            metadata={"atr": 2000},  # Higher ATR
        )

        sizer = PositionSizer(
            strategy=SizingStrategy.VOLATILITY_BASED,
            risk_per_trade=Decimal("0.02"),
            volatility_multiplier=Decimal("2.0"),
        )

        quantity = sizer.calculate_position_size(execution_context, signal, OrderSide.BUY)

        # Risk amount = 200
        # Volatility risk = 2000 * 2.0 = 4000
        # Position size = 200 / 4000 = 0.05 BTC (smaller due to high volatility)
        assert quantity == Decimal("0.05")

    def test_volatility_based_no_atr_fallback(self, execution_context, buy_signal):
        """Test fallback to fixed fractional when ATR not available."""
        # buy_signal doesn't have ATR in metadata
        sizer = PositionSizer(strategy=SizingStrategy.VOLATILITY_BASED)

        quantity = sizer.calculate_position_size(execution_context, buy_signal, OrderSide.BUY)

        # Should use fixed fractional as fallback
        # With stop-loss at 49000: position = 0.2 BTC
        assert quantity == Decimal("0.2")

    def test_volatility_based_zero_atr_fallback(self, execution_context):
        """Test fallback when ATR is zero."""
        signal = Signal(
            signal_type=SignalType.ENTRY_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.STRONG,
            metadata={"atr": 0},  # Zero ATR
            stop_loss=None,  # No stop loss
        )

        sizer = PositionSizer(
            strategy=SizingStrategy.VOLATILITY_BASED,
            default_stop_loss_pct=Decimal("0.02"),
        )

        quantity = sizer.calculate_position_size(execution_context, signal, OrderSide.BUY)

        # Should fallback to fixed fractional with default stop-loss (2%)
        # Default stop = 50000 * 0.98 = 49000
        # Risk per unit = 50000 - 49000 = 1000
        # Risk amount = 10000 * 0.02 = 200
        # Position size = 200 / 1000 = 0.2 BTC
        assert quantity == Decimal("0.2")


class TestKellyCriterionSizing:
    """Tests for Kelly Criterion position sizing."""

    def test_kelly_criterion_with_metrics(self, execution_context, buy_signal):
        """Test Kelly sizing with historical metrics."""
        sizer = PositionSizer(
            strategy=SizingStrategy.KELLY_CRITERION,
            kelly_fraction=Decimal("0.5"),  # Half-Kelly for this test
        )

        # Update with favorable metrics: 60% win rate, 2:1 reward/risk
        sizer.update_kelly_metrics(
            win_rate=Decimal("0.6"),
            avg_win=Decimal("200"),
            avg_loss=Decimal("100"),
        )

        quantity = sizer.calculate_position_size(execution_context, buy_signal, OrderSide.BUY)

        # Kelly = (0.6 * 2 - 0.4) / 2 = (1.2 - 0.4) / 2 = 0.4
        # Kelly safe = 0.4 * 0.5 = 0.2 (20% of balance)
        # Position value = 10000 * 0.2 = 2000
        # Position size = 2000 / 50000 = 0.04 BTC
        assert quantity == Decimal("0.04")

    def test_kelly_criterion_without_metrics_fallback(self, execution_context, buy_signal):
        """Test fallback to fixed fractional when no metrics available."""
        sizer = PositionSizer(strategy=SizingStrategy.KELLY_CRITERION)

        # No metrics updated
        quantity = sizer.calculate_position_size(execution_context, buy_signal, OrderSide.BUY)

        # Should use fixed fractional as fallback
        assert quantity == Decimal("0.2")

    def test_kelly_criterion_quarter_kelly(self, execution_context, buy_signal):
        """Test with quarter-Kelly (more conservative)."""
        sizer = PositionSizer(
            strategy=SizingStrategy.KELLY_CRITERION,
            kelly_fraction=Decimal("0.25"),  # Quarter-Kelly (default)
        )

        sizer.update_kelly_metrics(
            win_rate=Decimal("0.6"),
            avg_win=Decimal("200"),
            avg_loss=Decimal("100"),
        )

        quantity = sizer.calculate_position_size(execution_context, buy_signal, OrderSide.BUY)

        # Kelly full = 0.4
        # Kelly safe = 0.4 * 0.25 = 0.1 (10% of balance)
        # Position value = 10000 * 0.1 = 1000
        # Position size = 1000 / 50000 = 0.02 BTC
        assert quantity == Decimal("0.02")

    def test_kelly_criterion_poor_metrics(self, execution_context, buy_signal):
        """Test with poor win rate (negative Kelly)."""
        sizer = PositionSizer(
            strategy=SizingStrategy.KELLY_CRITERION,
            kelly_fraction=Decimal("0.25"),
            risk_per_trade=Decimal("0.02"),
        )

        # Update with poor metrics: 40% win rate, 1:1 reward/risk
        sizer.update_kelly_metrics(
            win_rate=Decimal("0.4"),
            avg_win=Decimal("100"),
            avg_loss=Decimal("100"),
        )

        quantity = sizer.calculate_position_size(execution_context, buy_signal, OrderSide.BUY)

        # Kelly = (0.4 * 1 - 0.6) / 1 = -0.2 (negative)
        # Kelly safe = -0.2 * 0.25 = -0.05
        # Clamped to 0 (no position)
        assert quantity == Decimal("0")

    def test_kelly_criterion_clamped_to_max(self, execution_context, buy_signal):
        """Test Kelly clamping to max (100% of balance)."""
        sizer = PositionSizer(
            strategy=SizingStrategy.KELLY_CRITERION,
            kelly_fraction=Decimal("1.0"),  # Full Kelly (aggressive)
            risk_per_trade=Decimal("0.02"),
        )

        # Very favorable metrics: 80% win rate, 3:1 reward/risk
        sizer.update_kelly_metrics(
            win_rate=Decimal("0.8"),
            avg_win=Decimal("300"),
            avg_loss=Decimal("100"),
        )

        quantity = sizer.calculate_position_size(execution_context, buy_signal, OrderSide.BUY)

        # Kelly = (0.8 * 3 - 0.2) / 3 = (2.4 - 0.2) / 3 = 0.7333...
        # Kelly safe = 0.7333... * 1.0 = 0.7333... (73.33% of balance)
        # Not clamped (< 100%)
        # Position value = 10000 * 0.7333... = 7333.33...
        # Position size = 7333.33... / 50000 = 0.14666667 BTC (rounded to 8 decimals)
        assert quantity == Decimal("0.14666667")


class TestSellOrders:
    """Tests for sell order quantity calculation."""

    def test_sell_uses_position_size(self, execution_context, sell_signal):
        """Test that sell orders use existing position size."""
        # Set position in context
        execution_context.has_position = True
        execution_context.position_size = Decimal("0.5")

        sizer = PositionSizer(strategy=SizingStrategy.FIXED_FRACTIONAL)

        quantity = sizer.calculate_position_size(execution_context, sell_signal, OrderSide.SELL)

        # Should return position size, not calculate new
        assert quantity == Decimal("0.5")

    def test_sell_no_position_returns_zero(self, execution_context, sell_signal):
        """Test that sell with no position returns zero."""
        # No position
        execution_context.has_position = False

        sizer = PositionSizer(strategy=SizingStrategy.FIXED_FRACTIONAL)

        quantity = sizer.calculate_position_size(execution_context, sell_signal, OrderSide.SELL)

        assert quantity == Decimal("0")


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_unknown_strategy_fallback(self, execution_context, buy_signal):
        """Test handling of unknown strategy (shouldn't happen)."""
        sizer = PositionSizer(strategy=SizingStrategy.FIXED_FRACTIONAL)
        # Manually set invalid strategy
        sizer._strategy = "invalid_strategy"  # type: ignore

        quantity = sizer.calculate_position_size(execution_context, buy_signal, OrderSide.BUY)

        # Should fallback to fixed fractional
        assert quantity == Decimal("0.2")

    def test_rounding_to_8_decimals(self, execution_context, buy_signal):
        """Test that all results are rounded to 8 decimal places."""
        sizer = PositionSizer(
            strategy=SizingStrategy.FIXED_FRACTIONAL,
            risk_per_trade=Decimal("0.023456789"),
        )

        quantity = sizer.calculate_position_size(execution_context, buy_signal, OrderSide.BUY)

        # Check that result has max 8 decimal places
        assert quantity == quantity.quantize(Decimal("0.00000001"))

    def test_very_small_balance(self, buy_signal):
        """Test with very small account balance."""
        context = ExecutionContext(
            symbol="BTC-USD",
            current_price=Decimal("50000"),
            timestamp=datetime.now(UTC),
            account_balance=Decimal("10"),  # Only $10
            available_balance=Decimal("10"),
            has_position=False,
            position_size=Decimal("0"),
        )

        sizer = PositionSizer(
            strategy=SizingStrategy.FIXED_FRACTIONAL,
            risk_per_trade=Decimal("0.02"),
        )

        quantity = sizer.calculate_position_size(context, buy_signal, OrderSide.BUY)

        # Risk amount = 10 * 0.02 = 0.2
        # Risk per unit = 1000
        # Position size = 0.2 / 1000 = 0.0002 BTC
        assert quantity == Decimal("0.0002")

    def test_update_kelly_metrics(self):
        """Test updating Kelly metrics."""
        sizer = PositionSizer(strategy=SizingStrategy.KELLY_CRITERION)

        # Initially None
        assert sizer._win_rate is None
        assert sizer._avg_win is None
        assert sizer._avg_loss is None

        # Update metrics
        sizer.update_kelly_metrics(
            win_rate=Decimal("0.6"),
            avg_win=Decimal("200"),
            avg_loss=Decimal("100"),
        )

        # Check updated
        assert sizer._win_rate == Decimal("0.6")
        assert sizer._avg_win == Decimal("200")
        assert sizer._avg_loss == Decimal("100")
