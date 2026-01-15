"""Slippage and fee models for realistic backtesting.

This module implements slippage and trading fee calculation models
to simulate realistic order execution in backtests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING

from cryptrink.core.logging import get_logger

if TYPE_CHECKING:
    from cryptrink.execution.base import OrderSide
    from cryptrink.strategies.base import Signal

logger = get_logger(__name__)


class SlippageModel(ABC):
    """Abstract base class for slippage models.

    Slippage models simulate the difference between expected and actual
    execution prices due to market impact and order timing.
    """

    @abstractmethod
    def apply_slippage(
        self,
        price: Decimal,
        signal: Signal,
        order_side: OrderSide,
    ) -> Decimal:
        """Apply slippage to execution price.

        Args:
            price: Original order price.
            signal: Trading signal with metadata.
            order_side: Order side (BUY or SELL).

        Returns:
            Adjusted execution price after slippage.
        """


class ConstantSlippageModel(SlippageModel):
    """Fixed basis points (bps) slippage model.

    Applies a constant slippage percentage to all orders:
    - Long/Buy: execution_price = price * (1 + slippage_bps)
    - Short/Sell: execution_price = price * (1 - slippage_bps)

    This is a simple, conservative slippage model suitable for liquid markets.
    """

    def __init__(self, slippage_bps: Decimal = Decimal("0.0005")) -> None:
        """Initialize constant slippage model.

        Args:
            slippage_bps: Slippage in basis points (e.g., 0.0005 = 5 bps = 0.05%).
                Default is 5 bps, realistic for major crypto pairs (BTC, ETH).
        """
        self._slippage_bps = slippage_bps

        logger.info(
            "constant_slippage_model_initialized",
            slippage_bps=float(slippage_bps),
            slippage_pct=float(slippage_bps * 100),
        )

    def apply_slippage(
        self,
        price: Decimal,
        signal: Signal,
        order_side: OrderSide,
    ) -> Decimal:
        """Apply constant slippage to execution price.

        Args:
            price: Original order price.
            signal: Trading signal (unused in this model).
            order_side: Order side (BUY or SELL).

        Returns:
            Adjusted execution price:
            - BUY: price * (1 + slippage_bps) (worse price, higher)
            - SELL: price * (1 - slippage_bps) (worse price, lower)
        """
        from cryptrink.execution.base import OrderSide

        if order_side == OrderSide.BUY:
            # Buy at higher price (worse for buyer)
            execution_price = price * (Decimal("1") + self._slippage_bps)
        else:  # SELL
            # Sell at lower price (worse for seller)
            execution_price = price * (Decimal("1") - self._slippage_bps)

        logger.debug(
            "slippage_applied",
            original_price=float(price),
            execution_price=float(execution_price),
            order_side=order_side.value,
            slippage_bps=float(self._slippage_bps),
        )

        return execution_price

    @property
    def slippage_bps(self) -> Decimal:
        """Get slippage in basis points."""
        return self._slippage_bps

    def __repr__(self) -> str:
        """Return string representation."""
        return f"ConstantSlippageModel(slippage_bps={float(self._slippage_bps)})"


class PercentageSlippageModel(SlippageModel):
    """Percentage-based slippage model.

    Similar to ConstantSlippageModel but allows different slippage
    percentages for buy and sell orders.
    """

    def __init__(
        self,
        buy_slippage_pct: Decimal = Decimal("0.001"),
        sell_slippage_pct: Decimal = Decimal("0.001"),
    ) -> None:
        """Initialize percentage slippage model.

        Args:
            buy_slippage_pct: Slippage percentage for buy orders (e.g., 0.001 = 0.1%).
            sell_slippage_pct: Slippage percentage for sell orders (e.g., 0.001 = 0.1%).
        """
        self._buy_slippage_pct = buy_slippage_pct
        self._sell_slippage_pct = sell_slippage_pct

        logger.info(
            "percentage_slippage_model_initialized",
            buy_slippage_pct=float(buy_slippage_pct * 100),
            sell_slippage_pct=float(sell_slippage_pct * 100),
        )

    def apply_slippage(
        self,
        price: Decimal,
        signal: Signal,
        order_side: OrderSide,
    ) -> Decimal:
        """Apply percentage-based slippage to execution price.

        Args:
            price: Original order price.
            signal: Trading signal (unused in this model).
            order_side: Order side (BUY or SELL).

        Returns:
            Adjusted execution price with side-specific slippage.
        """
        from cryptrink.execution.base import OrderSide

        if order_side == OrderSide.BUY:
            # Buy at higher price
            execution_price = price * (Decimal("1") + self._buy_slippage_pct)
        else:  # SELL
            # Sell at lower price
            execution_price = price * (Decimal("1") - self._sell_slippage_pct)

        logger.debug(
            "percentage_slippage_applied",
            original_price=float(price),
            execution_price=float(execution_price),
            order_side=order_side.value,
            slippage_pct=float(
                self._buy_slippage_pct if order_side == OrderSide.BUY else self._sell_slippage_pct
            )
            * 100,
        )

        return execution_price

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"PercentageSlippageModel("
            f"buy_slippage={float(self._buy_slippage_pct * 100):.2f}%, "
            f"sell_slippage={float(self._sell_slippage_pct * 100):.2f}%)"
        )


class FeeModel(ABC):
    """Abstract base class for trading fee models.

    Fee models calculate trading fees based on order size and side.
    """

    @abstractmethod
    def calculate_fee(
        self,
        quantity: Decimal,
        price: Decimal,
        order_side: OrderSide,
    ) -> Decimal:
        """Calculate trading fee for an order.

        Args:
            quantity: Order quantity in base currency units.
            price: Execution price.
            order_side: Order side (BUY or SELL).

        Returns:
            Trading fee in quote currency.
        """


class PercentageFeeModel(FeeModel):
    """Simple percentage-based fee model.

    Applies a fixed percentage fee to the notional value of each order:
    - Fee = quantity * price * fee_pct

    This matches most exchange fee structures (e.g., RevolutX: 0.09% taker fee).
    """

    def __init__(self, fee_pct: Decimal = Decimal("0.0009")) -> None:
        """Initialize percentage fee model.

        Args:
            fee_pct: Fee percentage (e.g., 0.0009 = 0.09%).
                Default is 0.09%, matching RevolutX taker fee.
        """
        self._fee_pct = fee_pct

        logger.info(
            "percentage_fee_model_initialized",
            fee_pct=float(fee_pct * 100),
        )

    def calculate_fee(
        self,
        quantity: Decimal,
        price: Decimal,
        order_side: OrderSide,
    ) -> Decimal:
        """Calculate percentage-based trading fee.

        Args:
            quantity: Order quantity in base currency units.
            price: Execution price.
            order_side: Order side (unused - same fee for buy/sell).

        Returns:
            Trading fee = quantity * price * fee_pct.
        """
        notional_value = quantity * price
        fee = notional_value * self._fee_pct

        logger.debug(
            "fee_calculated",
            quantity=float(quantity),
            price=float(price),
            notional_value=float(notional_value),
            fee=float(fee),
            fee_pct=float(self._fee_pct * 100),
        )

        return fee

    @property
    def fee_pct(self) -> Decimal:
        """Get fee percentage."""
        return self._fee_pct

    def __repr__(self) -> str:
        """Return string representation."""
        return f"PercentageFeeModel(fee_pct={float(self._fee_pct * 100):.2f}%)"
