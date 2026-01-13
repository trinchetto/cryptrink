"""Mean reversion trading strategies.

This module implements strategies that profit from price reversals back to
mean or equilibrium levels, such as RSI-based and Bollinger Bands strategies.
"""

from decimal import Decimal

from cryptrink.data.indicators import Indicators
from cryptrink.strategies.base import (
    BaseStrategy,
    Signal,
    SignalStrength,
    SignalType,
    StrategyContext,
)


class RsiMeanReversionStrategy(BaseStrategy):
    """RSI-based mean reversion strategy.

    This strategy generates buy signals when RSI indicates oversold conditions
    and sell signals when RSI indicates overbought conditions. It assumes that
    extreme RSI values will revert to the mean.

    Strategy Logic:
    - ENTRY_LONG: RSI < oversold_threshold (e.g., 30)
    - EXIT_LONG: RSI > overbought_threshold (e.g., 70)
    - Signal strength based on how extreme the RSI value is

    Parameters:
        rsi_period: Period for RSI calculation (default: 14)
        oversold_threshold: RSI level considered oversold (default: 30)
        overbought_threshold: RSI level considered overbought (default: 70)
        extreme_oversold: Threshold for strong oversold signal (default: 20)
        extreme_overbought: Threshold for strong overbought signal (default: 80)
    """

    def __init__(
        self,
        rsi_period: int = 14,
        oversold_threshold: float = 30.0,
        overbought_threshold: float = 70.0,
        extreme_oversold: float = 20.0,
        extreme_overbought: float = 80.0,
    ) -> None:
        """Initialize RSI Mean Reversion strategy.

        Args:
            rsi_period: Period for RSI calculation (must be >= 2).
            oversold_threshold: RSI level to trigger buy signal.
            overbought_threshold: RSI level to trigger sell signal.
            extreme_oversold: RSI level for strong buy signal.
            extreme_overbought: RSI level for strong sell signal.

        Raises:
            ValueError: If parameters are invalid.
        """
        if rsi_period < 2:
            raise ValueError(f"rsi_period must be >= 2, got {rsi_period}")
        if not 0 <= oversold_threshold <= 100:
            raise ValueError(
                f"oversold_threshold must be between 0 and 100, got {oversold_threshold}"
            )
        if not 0 <= overbought_threshold <= 100:
            raise ValueError(
                f"overbought_threshold must be between 0 and 100, got {overbought_threshold}"
            )
        if oversold_threshold >= overbought_threshold:
            raise ValueError(
                f"oversold_threshold ({oversold_threshold}) must be < "
                f"overbought_threshold ({overbought_threshold})"
            )
        if extreme_oversold >= oversold_threshold:
            raise ValueError(
                f"extreme_oversold ({extreme_oversold}) must be < "
                f"oversold_threshold ({oversold_threshold})"
            )
        if extreme_overbought <= overbought_threshold:
            raise ValueError(
                f"extreme_overbought ({extreme_overbought}) must be > "
                f"overbought_threshold ({overbought_threshold})"
            )

        self._rsi_period = rsi_period
        self._oversold_threshold = Decimal(str(oversold_threshold))
        self._overbought_threshold = Decimal(str(overbought_threshold))
        self._extreme_oversold = Decimal(str(extreme_oversold))
        self._extreme_overbought = Decimal(str(extreme_overbought))

    @property
    def name(self) -> str:
        """Strategy name."""
        return f"rsi_mean_reversion_{self._rsi_period}"

    @property
    def description(self) -> str:
        """Strategy description."""
        return (
            f"RSI Mean Reversion strategy with period={self._rsi_period}, "
            f"oversold={self._oversold_threshold}, overbought={self._overbought_threshold}"
        )

    @property
    def required_history(self) -> int:
        """Number of candles required for strategy.

        Need at least rsi_period + buffer for reliable signals.
        """
        return self._rsi_period + 20

    @property
    def timeframe(self) -> str:
        """Preferred timeframe.

        RSI mean reversion works well on 1h or 4h timeframes.
        """
        return "1h"

    def generate_signal(self, context: StrategyContext) -> Signal:
        """Generate trading signal based on RSI levels.

        Args:
            context: Current market context with OHLCV data.

        Returns:
            Trading signal (ENTRY_LONG, EXIT_LONG, or HOLD).
        """
        # Validate context
        if not self.validate_context(context):
            return self._create_hold_signal(context, reason="insufficient_candles")

        # Calculate RSI
        close_prices = context.ohlcv["close"]
        rsi = Indicators.rsi(close_prices, self._rsi_period)

        # Get current RSI value - check for NaN
        import pandas as pd

        if pd.isna(rsi.iloc[-1]):
            return self._create_hold_signal(context, reason="nan_rsi_value")

        current_rsi = Decimal(str(rsi.iloc[-1]))

        # Determine signal type and strength
        signal_type = SignalType.HOLD
        strength = SignalStrength.WEAK

        # Oversold condition - potential buy signal
        if current_rsi < self._oversold_threshold:
            if not context.has_position:
                signal_type = SignalType.ENTRY_LONG
                strength = self._calculate_oversold_strength(current_rsi)
            else:
                # Already in position, hold
                signal_type = SignalType.HOLD

        # Overbought condition - potential sell signal
        elif current_rsi > self._overbought_threshold:
            if context.has_position:
                signal_type = SignalType.EXIT_LONG
                strength = self._calculate_overbought_strength(current_rsi)
            else:
                # Not in position, hold
                signal_type = SignalType.HOLD

        # Neutral RSI - hold
        else:
            signal_type = SignalType.HOLD

        # Create signal with metadata
        return Signal(
            signal_type=signal_type,
            symbol=context.symbol,
            strength=strength,
            timestamp=context.timestamp,
            price=context.current_price,
            metadata={
                "rsi": float(current_rsi),
                "oversold_threshold": float(self._oversold_threshold),
                "overbought_threshold": float(self._overbought_threshold),
                "rsi_period": self._rsi_period,
            },
        )

    def _calculate_oversold_strength(self, rsi: Decimal) -> SignalStrength:
        """Calculate signal strength for oversold conditions.

        Args:
            rsi: Current RSI value.

        Returns:
            Signal strength based on how oversold the RSI is.
        """
        # Strong: RSI < extreme_oversold (e.g., < 20)
        # Moderate: extreme_oversold <= RSI < (oversold + extreme)/2 (e.g., 20-25)
        # Weak: RSI >= mid_threshold (e.g., >= 25)
        if rsi < self._extreme_oversold:
            return SignalStrength.STRONG

        mid_threshold = (self._extreme_oversold + self._oversold_threshold) / 2
        if rsi < mid_threshold:
            return SignalStrength.MODERATE

        return SignalStrength.WEAK

    def _calculate_overbought_strength(self, rsi: Decimal) -> SignalStrength:
        """Calculate signal strength for overbought conditions.

        Args:
            rsi: Current RSI value.

        Returns:
            Signal strength based on how overbought the RSI is.
        """
        # Strong: RSI > extreme_overbought (e.g., > 80)
        # Moderate: (overbought + extreme)/2 < RSI <= extreme_overbought (e.g., 75-80)
        # Weak: RSI <= mid_threshold (e.g., <= 75)
        if rsi > self._extreme_overbought:
            return SignalStrength.STRONG

        mid_threshold = (self._overbought_threshold + self._extreme_overbought) / 2
        if rsi > mid_threshold:
            return SignalStrength.MODERATE

        return SignalStrength.WEAK

    def _create_hold_signal(self, context: StrategyContext, reason: str = "neutral_rsi") -> Signal:
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

        RSI strategy is stateless, so nothing to reset.
        """
        pass
