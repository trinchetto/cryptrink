"""Unit tests for fee models."""

from decimal import Decimal

from cryptrink.backtest.models import PercentageFeeModel
from cryptrink.execution.base import OrderSide


class TestPercentageFeeModel:
    """Tests for PercentageFeeModel."""

    def test_initialization_with_default(self):
        """Test initialization with default fee (0.09%)."""
        model = PercentageFeeModel()

        assert model.fee_pct == Decimal("0.0009")  # 0.09%

    def test_initialization_with_custom_fee(self):
        """Test initialization with custom fee."""
        model = PercentageFeeModel(fee_pct=Decimal("0.001"))

        assert model.fee_pct == Decimal("0.001")  # 0.1%

    def test_calculate_fee_for_buy_order(self):
        """Test fee calculation for buy order."""
        model = PercentageFeeModel(fee_pct=Decimal("0.001"))  # 0.1%
        quantity = Decimal("1.0")  # 1 BTC
        price = Decimal("50000")  # $50,000 per BTC

        fee = model.calculate_fee(quantity, price, OrderSide.BUY)

        # Notional = 1 * 50000 = 50000
        # Fee = 50000 * 0.001 = 50
        assert fee == Decimal("50")

    def test_calculate_fee_for_sell_order(self):
        """Test fee calculation for sell order (same as buy)."""
        model = PercentageFeeModel(fee_pct=Decimal("0.001"))  # 0.1%
        quantity = Decimal("1.0")  # 1 BTC
        price = Decimal("50000")  # $50,000 per BTC

        fee = model.calculate_fee(quantity, price, OrderSide.SELL)

        # Fee should be the same for sell
        assert fee == Decimal("50")

    def test_default_fee_0_09_percent(self):
        """Test default RevolutX taker fee (0.09%)."""
        model = PercentageFeeModel()  # Default 0.09%
        quantity = Decimal("2.0")  # 2 BTC
        price = Decimal("30000")  # $30,000 per BTC

        fee = model.calculate_fee(quantity, price, OrderSide.BUY)

        # Notional = 2 * 30000 = 60000
        # Fee = 60000 * 0.0009 = 54
        assert fee == Decimal("54")

    def test_zero_fee(self):
        """Test with zero fee (maker fee scenario)."""
        model = PercentageFeeModel(fee_pct=Decimal("0"))
        quantity = Decimal("1.0")
        price = Decimal("50000")

        fee = model.calculate_fee(quantity, price, OrderSide.BUY)

        assert fee == Decimal("0")

    def test_high_fee(self):
        """Test with high fee (1%)."""
        model = PercentageFeeModel(fee_pct=Decimal("0.01"))  # 1%
        quantity = Decimal("1.0")
        price = Decimal("50000")

        fee = model.calculate_fee(quantity, price, OrderSide.BUY)

        # Fee = 50000 * 0.01 = 500
        assert fee == Decimal("500")

    def test_small_order_fee(self):
        """Test fee for small order."""
        model = PercentageFeeModel(fee_pct=Decimal("0.001"))  # 0.1%
        quantity = Decimal("0.01")  # 0.01 BTC
        price = Decimal("50000")

        fee = model.calculate_fee(quantity, price, OrderSide.BUY)

        # Notional = 0.01 * 50000 = 500
        # Fee = 500 * 0.001 = 0.5
        assert fee == Decimal("0.5")

    def test_repr(self):
        """Test string representation."""
        model = PercentageFeeModel(fee_pct=Decimal("0.001"))

        repr_str = repr(model)

        assert "PercentageFeeModel" in repr_str
        assert "0.10%" in repr_str
