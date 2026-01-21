"""Unit tests for slippage models."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cryptrink.backtest.models import ConstantSlippageModel, PercentageSlippageModel
from cryptrink.execution.base import OrderSide
from cryptrink.strategies.base import Signal, SignalStrength, SignalType


@pytest.fixture
def buy_signal():
    """Create a buy signal."""
    return Signal(
        signal_type=SignalType.ENTRY_LONG,
        symbol="BTC-USD",
        timestamp=datetime.now(UTC),
        price=Decimal("50000"),
        strength=SignalStrength.STRONG,
    )


@pytest.fixture
def sell_signal():
    """Create a sell signal."""
    return Signal(
        signal_type=SignalType.EXIT_LONG,
        symbol="BTC-USD",
        timestamp=datetime.now(UTC),
        price=Decimal("50000"),
        strength=SignalStrength.STRONG,
    )


class TestConstantSlippageModel:
    """Tests for ConstantSlippageModel."""

    def test_initialization_with_default(self):
        """Test initialization with default slippage."""
        model = ConstantSlippageModel()

        assert model.slippage_bps == Decimal("0.0005")  # 5 bps

    def test_initialization_with_custom_slippage(self):
        """Test initialization with custom slippage."""
        model = ConstantSlippageModel(slippage_bps=Decimal("0.001"))

        assert model.slippage_bps == Decimal("0.001")  # 10 bps

    def test_apply_slippage_to_buy_order(self, buy_signal):
        """Test that buy orders get worse (higher) prices."""
        model = ConstantSlippageModel(slippage_bps=Decimal("0.001"))  # 10 bps = 0.1%
        price = Decimal("50000")

        execution_price = model.apply_slippage(price, buy_signal, OrderSide.BUY)

        # Buy should be 0.1% higher
        expected = price * Decimal("1.001")
        assert execution_price == expected
        assert execution_price == Decimal("50050")  # 50000 * 1.001

    def test_apply_slippage_to_sell_order(self, sell_signal):
        """Test that sell orders get worse (lower) prices."""
        model = ConstantSlippageModel(slippage_bps=Decimal("0.001"))  # 10 bps = 0.1%
        price = Decimal("50000")

        execution_price = model.apply_slippage(price, sell_signal, OrderSide.SELL)

        # Sell should be 0.1% lower
        expected = price * Decimal("0.999")
        assert execution_price == expected
        assert execution_price == Decimal("49950")  # 50000 * 0.999

    def test_default_slippage_5_bps(self, buy_signal):
        """Test default 5 bps slippage calculation."""
        model = ConstantSlippageModel()  # Default 5 bps
        price = Decimal("10000")

        execution_price = model.apply_slippage(price, buy_signal, OrderSide.BUY)

        # 5 bps = 0.05% = 0.0005
        expected = price * Decimal("1.0005")
        assert execution_price == expected
        assert execution_price == Decimal("10005")

    def test_zero_slippage(self, buy_signal):
        """Test with zero slippage."""
        model = ConstantSlippageModel(slippage_bps=Decimal("0"))
        price = Decimal("50000")

        execution_price = model.apply_slippage(price, buy_signal, OrderSide.BUY)

        # No slippage
        assert execution_price == price

    def test_large_slippage(self, buy_signal):
        """Test with large slippage (1%)."""
        model = ConstantSlippageModel(slippage_bps=Decimal("0.01"))  # 1%
        price = Decimal("50000")

        execution_price = model.apply_slippage(price, buy_signal, OrderSide.BUY)

        expected = price * Decimal("1.01")
        assert execution_price == expected
        assert execution_price == Decimal("50500")

    def test_repr(self):
        """Test string representation."""
        model = ConstantSlippageModel(slippage_bps=Decimal("0.001"))

        repr_str = repr(model)

        assert "ConstantSlippageModel" in repr_str
        assert "0.001" in repr_str


class TestPercentageSlippageModel:
    """Tests for PercentageSlippageModel."""

    def test_initialization_with_defaults(self):
        """Test initialization with default slippage."""
        model = PercentageSlippageModel()

        # Should not have public accessors, but we can verify behavior
        assert model is not None

    def test_initialization_with_custom_slippage(self):
        """Test initialization with custom buy/sell slippage."""
        model = PercentageSlippageModel(
            buy_slippage_pct=Decimal("0.002"),
            sell_slippage_pct=Decimal("0.003"),
        )

        assert model is not None

    def test_apply_slippage_to_buy_order(self, buy_signal):
        """Test buy order slippage."""
        model = PercentageSlippageModel(
            buy_slippage_pct=Decimal("0.002"),  # 0.2%
            sell_slippage_pct=Decimal("0.001"),  # Not used for buy
        )
        price = Decimal("50000")

        execution_price = model.apply_slippage(price, buy_signal, OrderSide.BUY)

        # Buy uses buy_slippage_pct
        expected = price * Decimal("1.002")
        assert execution_price == expected
        assert execution_price == Decimal("50100")

    def test_apply_slippage_to_sell_order(self, sell_signal):
        """Test sell order slippage."""
        model = PercentageSlippageModel(
            buy_slippage_pct=Decimal("0.001"),  # Not used for sell
            sell_slippage_pct=Decimal("0.003"),  # 0.3%
        )
        price = Decimal("50000")

        execution_price = model.apply_slippage(price, sell_signal, OrderSide.SELL)

        # Sell uses sell_slippage_pct
        expected = price * Decimal("0.997")
        assert execution_price == expected
        assert execution_price == Decimal("49850")

    def test_asymmetric_slippage(self, buy_signal, sell_signal):
        """Test different slippage for buy and sell."""
        model = PercentageSlippageModel(
            buy_slippage_pct=Decimal("0.001"),  # 0.1%
            sell_slippage_pct=Decimal("0.002"),  # 0.2%
        )
        price = Decimal("100000")

        buy_price = model.apply_slippage(price, buy_signal, OrderSide.BUY)
        sell_price = model.apply_slippage(price, sell_signal, OrderSide.SELL)

        assert buy_price == Decimal("100100")  # +0.1%
        assert sell_price == Decimal("99800")  # -0.2%
        assert buy_price > price
        assert sell_price < price

    def test_repr(self):
        """Test string representation."""
        model = PercentageSlippageModel(
            buy_slippage_pct=Decimal("0.001"),
            sell_slippage_pct=Decimal("0.002"),
        )

        repr_str = repr(model)

        assert "PercentageSlippageModel" in repr_str
        assert "0.10%" in repr_str  # buy slippage
        assert "0.20%" in repr_str  # sell slippage
