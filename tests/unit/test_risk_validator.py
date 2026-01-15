"""Unit tests for RiskValidator."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cryptrink.core.config import RiskSettings
from cryptrink.execution.base import ExecutionContext, OrderSide
from cryptrink.risk.metrics import RiskMetrics
from cryptrink.risk.validator import RiskValidator
from cryptrink.strategies.base import Signal, SignalStrength, SignalType


@pytest.fixture
def risk_settings():
    """Create default risk settings."""
    return RiskSettings(
        max_position_size_pct=0.1,
        max_open_positions=5,
        max_daily_loss_pct=0.05,
        max_drawdown_pct=0.15,
    )


@pytest.fixture
def validator(risk_settings):
    """Create RiskValidator with default settings."""
    return RiskValidator(risk_settings)


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
def risk_metrics():
    """Create risk metrics with zero values."""
    return RiskMetrics()


class TestRiskValidatorInitialization:
    """Tests for RiskValidator initialization."""

    def test_initialization_with_settings(self, risk_settings):
        """Test initialization with provided settings."""
        validator = RiskValidator(risk_settings)

        assert validator.settings == risk_settings
        assert validator.settings.max_position_size_pct == 0.1
        assert validator.settings.max_open_positions == 5

    def test_initialization_without_settings(self):
        """Test initialization with default settings."""
        validator = RiskValidator()

        assert validator.settings is not None
        assert isinstance(validator.settings, RiskSettings)

    def test_repr(self, validator):
        """Test string representation."""
        repr_str = repr(validator)

        assert "RiskValidator" in repr_str
        assert "0.1" in repr_str  # max_position_size
        assert "0.05" in repr_str  # max_daily_loss


class TestPositionSizeValidation:
    """Tests for position size validation."""

    def test_valid_position_size(self, validator, buy_signal, execution_context, risk_metrics):
        """Test that valid position size passes."""
        # Position: 0.01 BTC = $500 (5% of balance) < 10% max
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        assert result.valid is True
        assert result.reason == ""
        assert result.circuit_breaker_triggered is False

    def test_exceeds_max_position_size(
        self, validator, buy_signal, execution_context, risk_metrics
    ):
        """Test that position exceeding max is rejected."""
        # Position: 0.03 BTC = $1500 (15% of balance) > 10% max
        quantity = Decimal("0.03")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        assert result.valid is False
        assert "exceeds maximum" in result.reason
        assert result.circuit_breaker_triggered is False

    def test_exact_max_position_size(self, validator, buy_signal, execution_context, risk_metrics):
        """Test position at exact max limit."""
        # Position: 0.02 BTC = $1000 (10% of balance) = exactly at max
        quantity = Decimal("0.02")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        assert result.valid is True


class TestOpenPositionsValidation:
    """Tests for open positions count validation."""

    def test_below_max_open_positions(self, validator, buy_signal, execution_context, risk_metrics):
        """Test when below max open positions."""
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
            open_positions_count=3,
        )

        assert result.valid is True

    def test_at_max_open_positions(self, validator, buy_signal, execution_context, risk_metrics):
        """Test rejection when at max open positions."""
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
            open_positions_count=5,  # At max
        )

        assert result.valid is False
        assert "Open positions" in result.reason
        assert "maximum" in result.reason
        assert result.circuit_breaker_triggered is False

    def test_exceeds_max_open_positions(
        self, validator, buy_signal, execution_context, risk_metrics
    ):
        """Test rejection when exceeding max open positions."""
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
            open_positions_count=6,
        )

        assert result.valid is False
        assert "Open positions" in result.reason


class TestDailyLossValidation:
    """Tests for daily loss limit validation (circuit breaker)."""

    def test_no_daily_loss(self, validator, buy_signal, execution_context, risk_metrics):
        """Test when no daily loss."""
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        assert result.valid is True
        assert result.circuit_breaker_triggered is False

    def test_small_daily_loss(self, validator, buy_signal, execution_context, risk_metrics):
        """Test with small daily loss under limit."""
        # Daily loss = -$300 (3% of balance) < 5% max
        risk_metrics.daily_realized_pnl = Decimal("-300")
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        assert result.valid is True
        assert result.circuit_breaker_triggered is False

    def test_exceeds_daily_loss_limit(self, validator, buy_signal, execution_context, risk_metrics):
        """Test circuit breaker triggers when daily loss exceeds limit."""
        # Daily loss = -$600 (6% of balance) > 5% max
        risk_metrics.daily_realized_pnl = Decimal("-600")
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        assert result.valid is False
        assert "Daily loss limit exceeded" in result.reason
        assert result.circuit_breaker_triggered is True
        assert result.circuit_breaker_reason is not None
        assert "Daily loss" in result.circuit_breaker_reason

    def test_exact_daily_loss_limit(self, validator, buy_signal, execution_context, risk_metrics):
        """Test at exact daily loss limit."""
        # Daily loss = -$500 (5% of balance) = exactly at limit
        risk_metrics.daily_realized_pnl = Decimal("-500")
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        # Should still be valid (not exceeded)
        assert result.valid is True


class TestDrawdownValidation:
    """Tests for maximum drawdown validation (circuit breaker)."""

    def test_no_drawdown(self, validator, buy_signal, execution_context, risk_metrics):
        """Test when no drawdown."""
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        assert result.valid is True
        assert result.circuit_breaker_triggered is False

    def test_small_drawdown(self, validator, buy_signal, execution_context, risk_metrics):
        """Test with small drawdown under limit."""
        # Drawdown = 10% < 15% max
        risk_metrics.current_drawdown = Decimal("0.1")
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        assert result.valid is True
        assert result.circuit_breaker_triggered is False

    def test_exceeds_max_drawdown(self, validator, buy_signal, execution_context, risk_metrics):
        """Test circuit breaker triggers when drawdown exceeds limit."""
        # Drawdown = 20% > 15% max
        risk_metrics.current_drawdown = Decimal("0.2")
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        assert result.valid is False
        assert "Maximum drawdown exceeded" in result.reason
        assert result.circuit_breaker_triggered is True
        assert result.circuit_breaker_reason is not None
        assert "drawdown" in result.circuit_breaker_reason.lower()

    def test_exact_max_drawdown(self, validator, buy_signal, execution_context, risk_metrics):
        """Test at exact max drawdown limit."""
        # Drawdown = 15% = exactly at limit
        risk_metrics.current_drawdown = Decimal("0.15")
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        # Should still be valid (not exceeded)
        assert result.valid is True


class TestSellOrderValidation:
    """Tests for sell order validation."""

    def test_sell_orders_skip_validation(self, validator, execution_context, risk_metrics):
        """Test that sell orders skip all validation checks."""
        sell_signal = Signal(
            signal_type=SignalType.EXIT_LONG,
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            price=Decimal("50000"),
            strength=SignalStrength.STRONG,
        )

        # Set up worst-case scenario
        risk_metrics.daily_realized_pnl = Decimal("-1000")  # Exceeded daily loss
        risk_metrics.current_drawdown = Decimal("0.3")  # Exceeded drawdown

        quantity = Decimal("0.5")  # Large position

        result = validator.validate_order(
            sell_signal,
            quantity,
            execution_context,
            OrderSide.SELL,
            risk_metrics,
            open_positions_count=10,  # Exceeded open positions
        )

        # Sell should always be valid (allows closing positions)
        assert result.valid is True
        assert result.circuit_breaker_triggered is False


class TestCombinedValidation:
    """Tests for combined validation scenarios."""

    def test_multiple_violations_position_size_and_count(
        self, validator, buy_signal, execution_context, risk_metrics
    ):
        """Test that first violation is caught (position size checked before count)."""
        # Large position
        quantity = Decimal("0.5")  # 25% of balance > 10% max

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
            open_positions_count=10,  # Also exceeds
        )

        # Should fail on position size (checked first)
        assert result.valid is False
        assert "Position size" in result.reason

    def test_multiple_violations_circuit_breakers(
        self, validator, buy_signal, execution_context, risk_metrics
    ):
        """Test circuit breaker precedence when multiple limits exceeded."""
        # Small position size (passes size check)
        quantity = Decimal("0.01")

        # Both circuit breakers triggered
        risk_metrics.daily_realized_pnl = Decimal("-600")  # Exceeded daily loss
        risk_metrics.current_drawdown = Decimal("0.2")  # Exceeded drawdown

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        # Should fail on first circuit breaker (daily loss checked before drawdown)
        assert result.valid is False
        assert result.circuit_breaker_triggered is True
        assert "Daily loss" in result.circuit_breaker_reason

    def test_all_validations_pass(self, validator, buy_signal, execution_context, risk_metrics):
        """Test that order passes when all validations pass."""
        quantity = Decimal("0.01")  # 5% of balance
        risk_metrics.daily_realized_pnl = Decimal("-100")  # 1% loss
        risk_metrics.current_drawdown = Decimal("0.05")  # 5% drawdown

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
            open_positions_count=2,
        )

        assert result.valid is True
        assert result.reason == ""
        assert result.circuit_breaker_triggered is False
        assert result.circuit_breaker_reason is None


class TestCustomSettings:
    """Tests with custom risk settings."""

    def test_strict_position_limit(self, buy_signal, execution_context, risk_metrics):
        """Test with stricter position size limit."""
        strict_settings = RiskSettings(max_position_size_pct=0.05)  # 5% max
        validator = RiskValidator(strict_settings)

        # Position = 7% of balance
        quantity = Decimal("0.14")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        assert result.valid is False
        assert "exceeds maximum" in result.reason

    def test_lenient_daily_loss_limit(self, buy_signal, execution_context, risk_metrics):
        """Test with more lenient daily loss limit."""
        lenient_settings = RiskSettings(max_daily_loss_pct=0.10)  # 10% max
        validator = RiskValidator(lenient_settings)

        # Daily loss = 7% of balance
        risk_metrics.daily_realized_pnl = Decimal("-700")
        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
        )

        # Should pass with lenient limit
        assert result.valid is True

    def test_single_open_position_limit(self, buy_signal, execution_context, risk_metrics):
        """Test with max_open_positions=1."""
        single_position_settings = RiskSettings(max_open_positions=1)
        validator = RiskValidator(single_position_settings)

        quantity = Decimal("0.01")

        result = validator.validate_order(
            buy_signal,
            quantity,
            execution_context,
            OrderSide.BUY,
            risk_metrics,
            open_positions_count=1,
        )

        assert result.valid is False
        assert "Open positions" in result.reason
