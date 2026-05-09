"""Mean reversion trading strategies.

This module implements strategies that profit from price reversals back to
mean or equilibrium levels, such as RSI-based and Bollinger Bands strategies.
"""

from decimal import Decimal

import pandas as pd

from cryptrink.data.indicators import Indicators
from cryptrink.strategies.base import (
    BaseStrategy,
    ParameterSpec,
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

    @classmethod
    def param_schema(cls) -> list[ParameterSpec]:
        return [
            ParameterSpec(
                name="rsi_period",
                param_type=int,
                default=14,
                minimum=2,
                maximum=100,
                step=1,
                label="RSI period",
                help="Lookback window for RSI calculation.",
            ),
            ParameterSpec(
                name="oversold_threshold",
                param_type=float,
                default=30.0,
                minimum=5.0,
                maximum=49.0,
                step=1.0,
                label="Oversold threshold",
                help="RSI level that triggers an entry-long.",
            ),
            ParameterSpec(
                name="overbought_threshold",
                param_type=float,
                default=70.0,
                minimum=51.0,
                maximum=95.0,
                step=1.0,
                label="Overbought threshold",
                help="RSI level that triggers an exit-long.",
            ),
            ParameterSpec(
                name="extreme_oversold",
                param_type=float,
                default=20.0,
                minimum=1.0,
                maximum=48.0,
                step=1.0,
                label="Extreme oversold",
                help="RSI level for STRONG buy signal (must be < oversold).",
            ),
            ParameterSpec(
                name="extreme_overbought",
                param_type=float,
                default=80.0,
                minimum=52.0,
                maximum=99.0,
                step=1.0,
                label="Extreme overbought",
                help="RSI level for STRONG sell signal (must be > overbought).",
            ),
        ]


class BollingerBandsStrategy(BaseStrategy):
    """Bollinger Bands mean reversion strategy.

    This strategy generates buy signals when price touches or breaks below the
    lower Bollinger Band and sell signals when price touches or breaks above the
    upper Bollinger Band. It assumes prices will revert to the middle band (SMA).

    Strategy Logic:
    - ENTRY_LONG: Price <= lower_band (price breaks below lower band)
    - EXIT_LONG: Price >= upper_band (price breaks above upper band)
    - Signal strength based on distance from bands

    Parameters:
        period: Period for moving average and bands (default: 20)
        std_dev: Number of standard deviations for bands (default: 2.0)
        penetration_threshold: Percentage price must penetrate band (default: 0.001 = 0.1%)
    """

    def __init__(
        self,
        period: int = 20,
        std_dev: float = 2.0,
        penetration_threshold: float = 0.001,
    ) -> None:
        """Initialize Bollinger Bands strategy.

        Args:
            period: Period for SMA and standard deviation calculation (must be >= 2).
            std_dev: Number of standard deviations for bands (must be > 0).
            penetration_threshold: Minimum percentage penetration to trigger signal.

        Raises:
            ValueError: If parameters are invalid.
        """
        if period < 2:
            raise ValueError(f"period must be >= 2, got {period}")
        if std_dev <= 0:
            raise ValueError(f"std_dev must be > 0, got {std_dev}")
        if penetration_threshold < 0:
            raise ValueError(f"penetration_threshold must be >= 0, got {penetration_threshold}")

        self._period = period
        self._std_dev = Decimal(str(std_dev))
        self._penetration_threshold = Decimal(str(penetration_threshold))

    @property
    def name(self) -> str:
        """Strategy name."""
        # Format std_dev to remove unnecessary decimals (2.0 -> 2, 2.5 -> 2.5)
        std_dev_str = f"{float(self._std_dev):g}"
        return f"bollinger_bands_{self._period}_{std_dev_str}"

    @property
    def description(self) -> str:
        """Strategy description."""
        return (
            f"Bollinger Bands strategy with period={self._period}, "
            f"std_dev={self._std_dev}, threshold={self._penetration_threshold}"
        )

    @property
    def required_history(self) -> int:
        """Number of candles required for strategy.

        Need at least period + buffer for reliable signals.
        """
        return self._period + 10

    @property
    def timeframe(self) -> str:
        """Preferred timeframe.

        Bollinger Bands work well on 1h or 4h timeframes.
        """
        return "1h"

    def generate_signal(self, context: StrategyContext) -> Signal:
        """Generate trading signal based on Bollinger Bands.

        Args:
            context: Current market context with OHLCV data.

        Returns:
            Trading signal (ENTRY_LONG, EXIT_LONG, or HOLD).
        """
        # Validate context
        if not self.validate_context(context):
            return self._create_hold_signal(context, reason="insufficient_candles")

        # Calculate Bollinger Bands
        close_prices = context.ohlcv["close"]
        upper_band, middle_band, lower_band = Indicators.bollinger_bands(
            close_prices, period=self._period, std_dev=float(self._std_dev)
        )

        # Get current values - check for NaN
        if pd.isna(upper_band.iloc[-1]) or pd.isna(lower_band.iloc[-1]):
            return self._create_hold_signal(context, reason="nan_band_values")

        current_price = context.current_price
        current_upper = Decimal(str(upper_band.iloc[-1]))
        current_middle = Decimal(str(middle_band.iloc[-1]))
        current_lower = Decimal(str(lower_band.iloc[-1]))

        # Calculate band width (for signal strength)
        band_width = (current_upper - current_lower) / current_middle

        # Determine signal type and strength
        signal_type = SignalType.HOLD
        strength = SignalStrength.WEAK

        # Price below lower band - potential buy signal
        lower_penetration = (current_lower - current_price) / current_lower
        if lower_penetration >= self._penetration_threshold:
            if not context.has_position:
                signal_type = SignalType.ENTRY_LONG
                strength = self._calculate_penetration_strength(lower_penetration)
            else:
                # Already in position, hold
                signal_type = SignalType.HOLD

        # Price above upper band - potential sell signal
        upper_penetration = (current_price - current_upper) / current_upper
        if upper_penetration >= self._penetration_threshold:
            if context.has_position:
                signal_type = SignalType.EXIT_LONG
                strength = self._calculate_penetration_strength(upper_penetration)
            else:
                # Not in position, hold
                signal_type = SignalType.HOLD

        # Create signal with metadata
        return Signal(
            signal_type=signal_type,
            symbol=context.symbol,
            strength=strength,
            timestamp=context.timestamp,
            price=context.current_price,
            metadata={
                "upper_band": float(current_upper),
                "middle_band": float(current_middle),
                "lower_band": float(current_lower),
                "band_width": float(band_width),
                "current_price": float(current_price),
                "period": self._period,
                "std_dev": float(self._std_dev),
            },
        )

    def _calculate_penetration_strength(self, penetration_pct: Decimal) -> SignalStrength:
        """Calculate signal strength based on band penetration.

        Args:
            penetration_pct: Percentage price has penetrated the band.

        Returns:
            Signal strength based on penetration depth.
            - STRONG: > 1% penetration
            - MODERATE: 0.5% - 1% penetration
            - WEAK: 0.1% - 0.5% penetration
        """
        if penetration_pct > Decimal("0.01"):
            return SignalStrength.STRONG
        if penetration_pct > Decimal("0.005"):
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    def _create_hold_signal(self, context: StrategyContext, reason: str = "within_bands") -> Signal:
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

        Bollinger Bands strategy is stateless, so nothing to reset.
        """
        pass

    @classmethod
    def param_schema(cls) -> list[ParameterSpec]:
        return [
            ParameterSpec(
                name="period",
                param_type=int,
                default=20,
                minimum=2,
                maximum=200,
                step=1,
                label="Period",
                help="Lookback window for the SMA and the band width.",
            ),
            ParameterSpec(
                name="std_dev",
                param_type=float,
                default=2.0,
                minimum=0.5,
                maximum=5.0,
                step=0.1,
                label="Std deviations",
                help="Number of standard deviations for the upper / lower band.",
            ),
            ParameterSpec(
                name="penetration_threshold",
                param_type=float,
                default=0.001,
                minimum=0.0,
                maximum=0.05,
                step=0.0005,
                label="Penetration threshold",
                help="Minimum fractional band penetration to trigger a signal.",
            ),
        ]
