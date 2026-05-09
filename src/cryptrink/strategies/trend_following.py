"""Trend following trading strategies.

This module implements strategies that follow market trends, such as
moving average crossovers and breakout strategies.
"""

from decimal import Decimal

from cryptrink.data.indicators import Indicators
from cryptrink.strategies.base import (
    BaseStrategy,
    ParameterSpec,
    Signal,
    SignalStrength,
    SignalType,
    StrategyContext,
)


class SmaCrossoverStrategy(BaseStrategy):
    """Simple Moving Average (SMA) crossover strategy.

    This strategy generates buy signals when the fast SMA crosses above
    the slow SMA, and sell signals when the fast SMA crosses below the
    slow SMA. This is a classic trend-following strategy.

    Strategy Logic:
    - ENTRY_LONG: Fast SMA crosses above slow SMA (bullish crossover) when flat.
    - EXIT_LONG: Fast SMA crosses below slow SMA (bearish crossover) when long.
    - HOLD: any other state, including a bullish crossover while already long
      (the position is already aligned with the signal, so don't churn).
    - Signal strength based on distance between SMAs.

    Parameters:
        fast_period: Period for fast SMA (default: 10)
        slow_period: Period for slow SMA (default: 30)
        signal_threshold: Minimum percentage difference for signal (default: 0.001)
    """

    def __init__(
        self,
        fast_period: int = 10,
        slow_period: int = 30,
        signal_threshold: float = 0.001,
    ) -> None:
        """Initialize SMA Crossover strategy.

        Args:
            fast_period: Period for fast SMA (must be < slow_period).
            slow_period: Period for slow SMA (must be > fast_period).
            signal_threshold: Minimum percentage difference to generate signal.

        Raises:
            ValueError: If parameters are invalid.
        """
        if fast_period >= slow_period:
            raise ValueError(f"fast_period ({fast_period}) must be < slow_period ({slow_period})")
        if fast_period < 2:
            raise ValueError(f"fast_period must be >= 2, got {fast_period}")
        if signal_threshold < 0:
            raise ValueError(f"signal_threshold must be >= 0, got {signal_threshold}")

        self._fast_period = fast_period
        self._slow_period = slow_period
        self._signal_threshold = Decimal(str(signal_threshold))

        # Track previous SMA values for crossover detection
        self._prev_fast_sma: Decimal | None = None
        self._prev_slow_sma: Decimal | None = None

    @property
    def name(self) -> str:
        """Strategy name."""
        return f"sma_crossover_{self._fast_period}_{self._slow_period}"

    @property
    def description(self) -> str:
        """Strategy description."""
        return (
            f"SMA Crossover strategy with fast={self._fast_period}, "
            f"slow={self._slow_period}, threshold={self._signal_threshold}"
        )

    @property
    def required_history(self) -> int:
        """Number of candles required for strategy.

        Need at least slow_period + buffer for reliable signals.
        """
        return self._slow_period + 10

    @property
    def timeframe(self) -> str:
        """Preferred timeframe.

        SMA crossover works well on 1h timeframe.
        """
        return "1h"

    def generate_signal(self, context: StrategyContext) -> Signal:
        """Generate trading signal based on SMA crossover.

        Args:
            context: Current market context with OHLCV data.

        Returns:
            Trading signal (ENTRY_LONG, EXIT_LONG, or HOLD).
        """
        # Validate context
        if not self.validate_context(context):
            return self._create_hold_signal(context, reason="insufficient_candles")

        # Calculate SMAs
        close_prices = context.ohlcv["close"]
        fast_sma = Indicators.sma(close_prices, self._fast_period)
        slow_sma = Indicators.sma(close_prices, self._slow_period)

        # Get current SMA values - check for NaN
        import pandas as pd

        if pd.isna(fast_sma.iloc[-1]) or pd.isna(slow_sma.iloc[-1]):
            return self._create_hold_signal(context, reason="nan_sma_values")

        current_fast = Decimal(str(fast_sma.iloc[-1]))
        current_slow = Decimal(str(slow_sma.iloc[-1]))

        # Calculate percentage difference
        pct_diff = abs(current_fast - current_slow) / current_slow

        # Detect crossover by comparing with previous values
        signal_type = SignalType.HOLD
        strength = SignalStrength.WEAK

        if self._prev_fast_sma is not None and self._prev_slow_sma is not None:
            # Bullish crossover: fast crosses above slow → enter long if flat,
            # otherwise hold (the existing position is already aligned with the
            # signal, so don't churn).
            if (
                self._prev_fast_sma <= self._prev_slow_sma
                and current_fast > current_slow
                and pct_diff >= self._signal_threshold
            ):
                signal_type = SignalType.HOLD if context.has_position else SignalType.ENTRY_LONG
                strength = self._calculate_signal_strength(pct_diff)

            # Bearish crossover: fast crosses below slow → exit long if we're
            # in a position, otherwise hold.
            elif (
                self._prev_fast_sma >= self._prev_slow_sma
                and current_fast < current_slow
                and pct_diff >= self._signal_threshold
            ):
                signal_type = SignalType.EXIT_LONG if context.has_position else SignalType.HOLD
                strength = self._calculate_signal_strength(pct_diff)

        # Update previous values for next iteration
        self._prev_fast_sma = current_fast
        self._prev_slow_sma = current_slow

        # Create signal with metadata
        return Signal(
            signal_type=signal_type,
            symbol=context.symbol,
            strength=strength,
            timestamp=context.timestamp,
            price=context.current_price,
            metadata={
                "fast_sma": float(current_fast),
                "slow_sma": float(current_slow),
                "pct_diff": float(pct_diff),
                "threshold": float(self._signal_threshold),
            },
        )

    def _calculate_signal_strength(self, pct_diff: Decimal) -> SignalStrength:
        """Calculate signal strength based on percentage difference.

        Args:
            pct_diff: Percentage difference between fast and slow SMA.

        Returns:
            Signal strength classification.
        """
        # Define thresholds for strength
        # Weak: 0.1% - 0.5%
        # Moderate: 0.5% - 1.5%
        # Strong: > 1.5%
        if pct_diff < Decimal("0.005"):
            return SignalStrength.WEAK
        if pct_diff < Decimal("0.015"):
            return SignalStrength.MODERATE
        return SignalStrength.STRONG

    def _create_hold_signal(self, context: StrategyContext, reason: str = "no_crossover") -> Signal:
        """Create a HOLD signal.

        Args:
            context: Current market context.
            reason: Reason for the HOLD signal.

        Returns:
            HOLD signal with current price.
        """
        return Signal(
            signal_type=SignalType.HOLD,
            symbol=context.symbol,
            strength=SignalStrength.WEAK,
            timestamp=context.timestamp,
            price=context.current_price,
            metadata={"reason": reason},
        )

    def reset(self) -> None:
        """Reset strategy state.

        Clears previous SMA values for fresh start.
        """
        self._prev_fast_sma = None
        self._prev_slow_sma = None

    @classmethod
    def param_schema(cls) -> list[ParameterSpec]:
        return [
            ParameterSpec(
                name="fast_period",
                param_type=int,
                default=10,
                minimum=2,
                maximum=100,
                step=1,
                label="Fast period",
                help="Window of the fast SMA (must be < slow period).",
            ),
            ParameterSpec(
                name="slow_period",
                param_type=int,
                default=30,
                minimum=3,
                maximum=300,
                step=1,
                label="Slow period",
                help="Window of the slow SMA (must be > fast period).",
            ),
            ParameterSpec(
                name="signal_threshold",
                param_type=float,
                default=0.001,
                minimum=0.0,
                maximum=0.05,
                step=0.0005,
                label="Signal threshold",
                help="Minimum fractional gap between SMAs to register a crossover.",
            ),
        ]
