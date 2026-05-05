"""Position sizing algorithms for risk-based trade sizing.

This module implements multiple position sizing strategies to calculate
appropriate trade quantities based on account risk parameters.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from cryptrink.core.logging import get_logger

if TYPE_CHECKING:
    from cryptrink.execution.base import ExecutionContext, OrderSide
    from cryptrink.strategies.base import Signal

logger = get_logger(__name__)


class SizingStrategy(StrEnum):
    """Position sizing strategy.

    - FIXED_FRACTIONAL: Risk a fixed percentage per trade based on stop-loss distance
    - VOLATILITY_BASED: Scale position size inversely with market volatility (ATR)
    - KELLY_CRITERION: Optimal sizing based on win rate and risk/reward ratio
    """

    FIXED_FRACTIONAL = "fixed_fractional"
    VOLATILITY_BASED = "volatility_based"
    KELLY_CRITERION = "kelly_criterion"


class PositionSizer:
    """Calculate position sizes based on risk management strategies.

    This class implements multiple position sizing algorithms that consider
    account balance, risk tolerance, and market conditions to determine
    appropriate trade quantities.
    """

    def __init__(
        self,
        strategy: SizingStrategy = SizingStrategy.FIXED_FRACTIONAL,
        risk_per_trade: Decimal = Decimal("0.02"),
        kelly_fraction: Decimal = Decimal("0.25"),
        volatility_multiplier: Decimal = Decimal("2.0"),
        default_stop_loss_pct: Decimal = Decimal("0.02"),
    ) -> None:
        """Initialize the position sizer.

        Args:
            strategy: Position sizing strategy to use.
            risk_per_trade: Percentage of account to risk per trade (0-1).
                Default 0.02 (2%).
            kelly_fraction: Fraction of Kelly criterion to use for safety.
                Default 0.25 (quarter-Kelly). Full Kelly can be aggressive.
            volatility_multiplier: Multiplier for ATR in volatility-based sizing.
                Default 2.0. Higher values = smaller positions in volatile markets.
            default_stop_loss_pct: Default stop-loss distance if not specified in signal.
                Default 0.02 (2%).
        """
        self._strategy = strategy
        self._risk_per_trade = risk_per_trade
        self._kelly_fraction = kelly_fraction
        self._volatility_multiplier = volatility_multiplier
        self._default_stop_loss_pct = default_stop_loss_pct

        # Kelly criterion requires historical metrics (win rate, avg win/loss)
        # These will be populated by RiskMetricsTracker in Phase 6.2
        self._win_rate: Decimal | None = None
        self._avg_win: Decimal | None = None
        self._avg_loss: Decimal | None = None

        logger.info(
            "position_sizer_initialized",
            strategy=strategy.value,
            risk_per_trade=float(risk_per_trade),
            kelly_fraction=float(kelly_fraction),
            volatility_multiplier=float(volatility_multiplier),
        )

    def calculate_position_size(
        self,
        context: ExecutionContext,
        signal: Signal,
        order_side: OrderSide,
    ) -> Decimal:
        """Calculate position size based on selected strategy.

        Args:
            context: Execution context with balance and price info.
            signal: Trading signal with stop-loss and other metadata.
            order_side: Order side (BUY or SELL).

        Returns:
            Position size in base currency units.
        """
        from cryptrink.execution.base import OrderSide

        # For sell orders, use position size (not calculated by risk)
        if order_side == OrderSide.SELL:
            if context.has_position and context.position_size > 0:
                return context.position_size
            return Decimal("0")

        # For buy orders, calculate based on strategy
        if self._strategy == SizingStrategy.FIXED_FRACTIONAL:
            return self._fixed_fractional_sizing(context, signal)
        elif self._strategy == SizingStrategy.VOLATILITY_BASED:
            return self._volatility_based_sizing(context, signal)
        elif self._strategy == SizingStrategy.KELLY_CRITERION:
            return self._kelly_criterion_sizing(context, signal)
        else:
            logger.warning(
                "unknown_sizing_strategy",
                strategy=str(self._strategy),
                fallback="fixed_fractional",
            )
            return self._fixed_fractional_sizing(context, signal)

    def _fixed_fractional_sizing(
        self,
        context: ExecutionContext,
        signal: Signal,
    ) -> Decimal:
        """Calculate position size using fixed fractional method.

        Formula: position_size = (balance * risk_pct) / abs(entry_price - stop_loss)

        This method risks a fixed percentage of the account balance on each trade.
        The position size is determined by the distance to the stop-loss.

        Args:
            context: Execution context with balance and price info.
            signal: Trading signal with optional stop-loss.

        Returns:
            Position size in base currency units.
        """
        # Determine stop-loss price
        if signal.stop_loss is not None and signal.stop_loss > 0:
            stop_loss_price = signal.stop_loss
        else:
            # Use default stop-loss distance (2% below entry for long)
            stop_loss_price = signal.price * (Decimal("1") - self._default_stop_loss_pct)

        # Calculate risk per share/unit
        risk_per_unit = abs(signal.price - stop_loss_price)

        if risk_per_unit == 0:
            logger.warning(
                "zero_risk_per_unit",
                symbol=signal.symbol,
                price=float(signal.price),
                stop_loss=float(stop_loss_price),
            )
            # Fallback to simple allocation
            return self._simple_allocation(context)

        # Calculate position size
        risk_amount = context.available_balance * self._risk_per_trade
        position_size = risk_amount / risk_per_unit

        # Round to 8 decimal places
        position_size = position_size.quantize(Decimal("0.00000001"))

        logger.debug(
            "fixed_fractional_sizing",
            symbol=signal.symbol,
            balance=float(context.available_balance),
            risk_pct=float(self._risk_per_trade),
            risk_amount=float(risk_amount),
            entry_price=float(signal.price),
            stop_loss=float(stop_loss_price),
            risk_per_unit=float(risk_per_unit),
            position_size=float(position_size),
        )

        return position_size

    def _volatility_based_sizing(
        self,
        context: ExecutionContext,
        signal: Signal,
    ) -> Decimal:
        """Calculate position size based on market volatility (ATR).

        Formula: position_size = (balance * risk_pct) / (ATR * multiplier)

        This method scales position size inversely with volatility.
        Higher volatility (larger ATR) results in smaller positions.

        Args:
            context: Execution context with balance and price info.
            signal: Trading signal with metadata (may contain ATR).

        Returns:
            Position size in base currency units.
        """
        # Try to get ATR from signal metadata
        atr = None
        if hasattr(signal, "metadata") and signal.metadata:
            atr_value = signal.metadata.get("atr")
            if atr_value is not None:
                atr = Decimal(str(atr_value))

        # If no ATR available, fall back to fixed fractional
        if atr is None or atr == 0:
            logger.warning(
                "no_atr_available",
                symbol=signal.symbol,
                fallback="fixed_fractional",
            )
            return self._fixed_fractional_sizing(context, signal)

        # Calculate position size based on volatility
        risk_amount = context.available_balance * self._risk_per_trade
        volatility_risk = atr * self._volatility_multiplier
        position_size = risk_amount / volatility_risk

        # Round to 8 decimal places
        position_size = position_size.quantize(Decimal("0.00000001"))

        logger.debug(
            "volatility_based_sizing",
            symbol=signal.symbol,
            balance=float(context.available_balance),
            risk_pct=float(self._risk_per_trade),
            atr=float(atr),
            volatility_multiplier=float(self._volatility_multiplier),
            position_size=float(position_size),
        )

        return position_size

    def _kelly_criterion_sizing(
        self,
        context: ExecutionContext,
        signal: Signal,
    ) -> Decimal:
        """Calculate position size using Kelly criterion.

        Formula: kelly_fraction = (win_rate - ((1-win_rate) / (avg_win/avg_loss)))
        Position size = balance * kelly_fraction * safety_factor

        This method calculates optimal position size based on historical
        win rate and risk/reward ratio. Requires sufficient trade history.

        Args:
            context: Execution context with balance and price info.
            signal: Trading signal.

        Returns:
            Position size in base currency units.
        """
        # Check if we have historical metrics
        if (
            self._win_rate is None
            or self._avg_win is None
            or self._avg_loss is None
            or self._avg_loss == 0
        ):
            logger.warning(
                "insufficient_kelly_metrics",
                symbol=signal.symbol,
                fallback="fixed_fractional",
                reason="Need win_rate, avg_win, avg_loss",
            )
            return self._fixed_fractional_sizing(context, signal)

        # Calculate Kelly fraction
        win_rate = self._win_rate
        loss_rate = Decimal("1") - win_rate
        win_loss_ratio = self._avg_win / self._avg_loss

        # Kelly formula: f = (p*b - q) / b
        # where p = win_rate, q = loss_rate, b = win/loss ratio
        kelly_full = (win_rate * win_loss_ratio - loss_rate) / win_loss_ratio

        # Apply safety factor (quarter-Kelly or half-Kelly)
        kelly_safe = kelly_full * self._kelly_fraction

        # Clamp to reasonable range [0, 1.0] (can't allocate more than 100%)
        kelly_safe = max(Decimal("0"), min(kelly_safe, Decimal("1.0")))

        # Calculate position size
        position_value = context.available_balance * kelly_safe
        position_size = position_value / signal.price

        # Round to 8 decimal places
        position_size = position_size.quantize(Decimal("0.00000001"))

        logger.debug(
            "kelly_criterion_sizing",
            symbol=signal.symbol,
            balance=float(context.available_balance),
            win_rate=float(win_rate),
            avg_win=float(self._avg_win),
            avg_loss=float(self._avg_loss),
            kelly_full=float(kelly_full),
            kelly_safe=float(kelly_safe),
            position_size=float(position_size),
        )

        return position_size

    def _simple_allocation(self, context: ExecutionContext) -> Decimal:
        """Fallback: simple percentage allocation.

        Uses 10% of available balance, matching Phase 5 behavior.

        Args:
            context: Execution context with balance and price info.

        Returns:
            Position size in base currency units.
        """
        allocation = Decimal("0.1")
        notional_value = context.available_balance * allocation
        quantity = notional_value / context.current_price
        return quantity.quantize(Decimal("0.00000001"))

    def update_kelly_metrics(
        self,
        win_rate: Decimal,
        avg_win: Decimal,
        avg_loss: Decimal,
    ) -> None:
        """Update Kelly criterion metrics from historical performance.

        This method will be called by RiskMetricsTracker in Phase 6.2.

        Args:
            win_rate: Win rate (0-1), e.g., 0.6 = 60% win rate.
            avg_win: Average winning trade size.
            avg_loss: Average losing trade size (positive value).
        """
        self._win_rate = win_rate
        self._avg_win = avg_win
        self._avg_loss = avg_loss

        logger.info(
            "kelly_metrics_updated",
            win_rate=float(win_rate),
            avg_win=float(avg_win),
            avg_loss=float(avg_loss),
        )

    @property
    def strategy(self) -> SizingStrategy:
        """Get the current sizing strategy."""
        return self._strategy

    @property
    def risk_per_trade(self) -> Decimal:
        """Get the risk per trade percentage."""
        return self._risk_per_trade

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"PositionSizer("
            f"strategy={self._strategy.value}, "
            f"risk_per_trade={float(self._risk_per_trade)}"
            ")"
        )
