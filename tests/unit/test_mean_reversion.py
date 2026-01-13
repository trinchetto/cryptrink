"""Unit tests for mean reversion strategies."""

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import pytest

from cryptrink.exchange.base import OrderSide
from cryptrink.strategies.base import SignalStrength, SignalType, StrategyContext
from cryptrink.strategies.mean_reversion import BollingerBandsStrategy, RsiMeanReversionStrategy


class TestRsiMeanReversionStrategy:
    """Tests for RSI Mean Reversion strategy."""

    def test_init_valid_parameters(self) -> None:
        """Test initialization with valid parameters."""
        strategy = RsiMeanReversionStrategy(
            rsi_period=14,
            oversold_threshold=30.0,
            overbought_threshold=70.0,
            extreme_oversold=20.0,
            extreme_overbought=80.0,
        )

        assert strategy.name == "rsi_mean_reversion_14"
        assert "period=14" in strategy.description
        assert "oversold=30" in strategy.description
        assert strategy.required_history == 34  # rsi_period + 20
        assert strategy.timeframe == "1h"

    def test_init_invalid_rsi_period(self) -> None:
        """Test that rsi_period must be >= 2."""
        with pytest.raises(ValueError, match="rsi_period must be >= 2"):
            RsiMeanReversionStrategy(rsi_period=1)

    def test_init_invalid_oversold_threshold(self) -> None:
        """Test that oversold_threshold must be between 0 and 100."""
        with pytest.raises(ValueError, match="oversold_threshold must be between 0 and 100"):
            RsiMeanReversionStrategy(oversold_threshold=-10.0)

        with pytest.raises(ValueError, match="oversold_threshold must be between 0 and 100"):
            RsiMeanReversionStrategy(oversold_threshold=110.0)

    def test_init_invalid_overbought_threshold(self) -> None:
        """Test that overbought_threshold must be between 0 and 100."""
        with pytest.raises(ValueError, match="overbought_threshold must be between 0 and 100"):
            RsiMeanReversionStrategy(overbought_threshold=-10.0)

        with pytest.raises(ValueError, match="overbought_threshold must be between 0 and 100"):
            RsiMeanReversionStrategy(overbought_threshold=110.0)

    def test_init_invalid_threshold_order(self) -> None:
        """Test that oversold_threshold must be less than overbought_threshold."""
        with pytest.raises(ValueError, match="oversold_threshold .* must be <"):
            RsiMeanReversionStrategy(oversold_threshold=70.0, overbought_threshold=30.0)

        with pytest.raises(ValueError, match="oversold_threshold .* must be <"):
            RsiMeanReversionStrategy(oversold_threshold=50.0, overbought_threshold=50.0)

    def test_init_invalid_extreme_oversold(self) -> None:
        """Test that extreme_oversold must be less than oversold_threshold."""
        with pytest.raises(ValueError, match="extreme_oversold .* must be <"):
            RsiMeanReversionStrategy(extreme_oversold=35.0, oversold_threshold=30.0)

    def test_init_invalid_extreme_overbought(self) -> None:
        """Test that extreme_overbought must be greater than overbought_threshold."""
        with pytest.raises(ValueError, match="extreme_overbought .* must be >"):
            RsiMeanReversionStrategy(extreme_overbought=65.0, overbought_threshold=70.0)

    def test_oversold_generates_entry_long(self) -> None:
        """Test that oversold RSI generates ENTRY_LONG signal."""
        strategy = RsiMeanReversionStrategy(
            rsi_period=14, oversold_threshold=30.0, overbought_threshold=70.0
        )

        # Create price data that results in low RSI (strong downtrend)
        # Start high, then decline sharply
        prices = list(range(130, 100, -1))  # 30 candles declining from 130 to 101
        # Need at least 34 candles (required_history)
        prices = [130] * 4 + prices  # Add padding at the start

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("101"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        # Should generate ENTRY_LONG in oversold condition
        assert signal.signal_type == SignalType.ENTRY_LONG
        assert signal.symbol == "BTC-USD"
        assert "rsi" in signal.metadata
        assert signal.metadata["rsi"] < 30.0  # Verify RSI is indeed oversold

    def test_overbought_generates_exit_long(self) -> None:
        """Test that overbought RSI generates EXIT_LONG when in position."""
        strategy = RsiMeanReversionStrategy(
            rsi_period=14, oversold_threshold=30.0, overbought_threshold=70.0
        )

        # Create price data that results in high RSI (strong uptrend)
        # Start low, then rise sharply
        prices = list(range(100, 130))  # 30 candles rising from 100 to 129
        # Need at least 34 candles (required_history)
        prices = [100] * 4 + prices  # Add padding at the start

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("129"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
            position_size=Decimal("1.0"),
            position_side=OrderSide.BUY,
            position_entry_price=Decimal("100"),
        )

        signal = strategy.generate_signal(context)

        # Should generate EXIT_LONG in overbought condition
        assert signal.signal_type == SignalType.EXIT_LONG
        assert signal.symbol == "BTC-USD"
        assert "rsi" in signal.metadata
        assert signal.metadata["rsi"] > 70.0  # Verify RSI is indeed overbought

    def test_neutral_rsi_generates_hold(self) -> None:
        """Test that neutral RSI generates HOLD signal."""
        strategy = RsiMeanReversionStrategy(
            rsi_period=14, oversold_threshold=30.0, overbought_threshold=70.0
        )

        # Create price data with neutral RSI (sideways movement)
        # Oscillating prices around 100
        prices = [100 + (i % 5) for i in range(40)]

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        # Should generate HOLD in neutral condition
        assert signal.signal_type == SignalType.HOLD
        assert signal.symbol == "BTC-USD"
        assert "rsi" in signal.metadata
        # RSI should be between oversold and overbought
        assert 30.0 <= signal.metadata["rsi"] <= 70.0

    def test_oversold_with_position_generates_hold(self) -> None:
        """Test that oversold RSI with existing position generates HOLD."""
        strategy = RsiMeanReversionStrategy(
            rsi_period=14, oversold_threshold=30.0, overbought_threshold=70.0
        )

        # Create price data that results in low RSI
        prices = list(range(130, 100, -1))
        prices = [130] * 4 + prices

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("101"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
            position_size=Decimal("1.0"),
            position_side=OrderSide.BUY,
            position_entry_price=Decimal("120"),
        )

        signal = strategy.generate_signal(context)

        # Should generate HOLD (already in position)
        assert signal.signal_type == SignalType.HOLD

    def test_overbought_without_position_generates_hold(self) -> None:
        """Test that overbought RSI without position generates HOLD."""
        strategy = RsiMeanReversionStrategy(
            rsi_period=14, oversold_threshold=30.0, overbought_threshold=70.0
        )

        # Create price data that results in high RSI
        prices = list(range(100, 130))
        prices = [100] * 4 + prices

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("129"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        # Should generate HOLD (not in position, can't exit)
        assert signal.signal_type == SignalType.HOLD

    def test_signal_strength_strong_oversold(self) -> None:
        """Test signal strength for extreme oversold condition."""
        strategy = RsiMeanReversionStrategy(
            rsi_period=14,
            oversold_threshold=30.0,
            overbought_threshold=70.0,
            extreme_oversold=20.0,
            extreme_overbought=80.0,
        )

        # Create very strong downtrend for extreme oversold RSI
        # Need at least 34 candles (required_history)
        prices = list(range(150, 100, -1))  # 50 candles declining from 150 to 101

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("101"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        # Very low RSI should result in STRONG signal if RSI < 20
        assert "rsi" in signal.metadata
        if signal.metadata["rsi"] < 20.0:
            assert signal.strength == SignalStrength.STRONG

    def test_signal_strength_strong_overbought(self) -> None:
        """Test signal strength for extreme overbought condition."""
        strategy = RsiMeanReversionStrategy(
            rsi_period=14,
            oversold_threshold=30.0,
            overbought_threshold=70.0,
            extreme_oversold=20.0,
            extreme_overbought=80.0,
        )

        # Create very strong uptrend for extreme overbought RSI
        # Need at least 34 candles (required_history)
        prices = list(range(100, 150))  # 50 candles rising from 100 to 149

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("149"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
            position_size=Decimal("1.0"),
            position_side=OrderSide.BUY,
            position_entry_price=Decimal("100"),
        )

        signal = strategy.generate_signal(context)

        # Very high RSI should result in STRONG signal if RSI > 80
        assert "rsi" in signal.metadata
        if signal.metadata["rsi"] > 80.0:
            assert signal.strength == SignalStrength.STRONG

    def test_insufficient_data_returns_hold(self) -> None:
        """Test that insufficient data returns HOLD signal."""
        strategy = RsiMeanReversionStrategy(rsi_period=14)

        # Only 10 candles - not enough (need 34)
        prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("109"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        assert signal.signal_type == SignalType.HOLD
        assert "reason" in signal.metadata
        assert signal.metadata["reason"] == "insufficient_candles"

    def test_empty_dataframe_returns_hold(self) -> None:
        """Test that empty DataFrame returns HOLD signal."""
        strategy = RsiMeanReversionStrategy(rsi_period=14)

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100"),
            timestamp=datetime.now(UTC),
            ohlcv=pd.DataFrame(),
        )

        signal = strategy.generate_signal(context)

        assert signal.signal_type == SignalType.HOLD

    def test_reset_is_noop(self) -> None:
        """Test that reset does nothing (strategy is stateless)."""
        strategy = RsiMeanReversionStrategy(rsi_period=14)

        # Reset should not raise an error
        strategy.reset()

        # Strategy should still work normally after reset
        prices = [100 + i for i in range(40)]
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("140"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)
        assert signal.symbol == "BTC-USD"

    def test_metadata_contains_rsi_values(self) -> None:
        """Test that signal metadata contains RSI values."""
        strategy = RsiMeanReversionStrategy(rsi_period=14)

        # Create enough data
        prices = [100 + i for i in range(40)]
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("140"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        assert "rsi" in signal.metadata
        assert "oversold_threshold" in signal.metadata
        assert "overbought_threshold" in signal.metadata
        assert "rsi_period" in signal.metadata
        assert isinstance(signal.metadata["rsi"], float)
        assert 0 <= signal.metadata["rsi"] <= 100

    def test_custom_parameters(self) -> None:
        """Test strategy with custom parameters."""
        strategy = RsiMeanReversionStrategy(
            rsi_period=7,
            oversold_threshold=25.0,
            overbought_threshold=75.0,
            extreme_oversold=15.0,
            extreme_overbought=85.0,
        )

        assert strategy.name == "rsi_mean_reversion_7"
        assert strategy.required_history == 27  # 7 + 20

        # Verify thresholds are used correctly
        prices = [100 + i for i in range(30)]
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("130"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        assert signal.metadata["oversold_threshold"] == 25.0
        assert signal.metadata["overbought_threshold"] == 75.0
        assert signal.metadata["rsi_period"] == 7

    def test_context_validation(self) -> None:
        """Test that context validation works correctly."""
        strategy = RsiMeanReversionStrategy(rsi_period=14)

        # Test with None ohlcv
        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100"),
            timestamp=datetime.now(UTC),
            ohlcv=None,  # type: ignore
        )

        signal = strategy.generate_signal(context)
        assert signal.signal_type == SignalType.HOLD


class TestBollingerBandsStrategy:
    """Tests for Bollinger Bands strategy."""

    def test_init_valid_parameters(self) -> None:
        """Test initialization with valid parameters."""
        strategy = BollingerBandsStrategy(period=20, std_dev=2.0, penetration_threshold=0.001)

        assert strategy.name == "bollinger_bands_20_2"
        assert "period=20" in strategy.description
        assert "std_dev=2" in strategy.description
        assert strategy.required_history == 30  # period + 10
        assert strategy.timeframe == "1h"

    def test_init_invalid_period(self) -> None:
        """Test that period must be >= 2."""
        with pytest.raises(ValueError, match="period must be >= 2"):
            BollingerBandsStrategy(period=1)

    def test_init_invalid_std_dev(self) -> None:
        """Test that std_dev must be > 0."""
        with pytest.raises(ValueError, match="std_dev must be > 0"):
            BollingerBandsStrategy(std_dev=0)

        with pytest.raises(ValueError, match="std_dev must be > 0"):
            BollingerBandsStrategy(std_dev=-1.0)

    def test_init_invalid_threshold(self) -> None:
        """Test that penetration_threshold must be >= 0."""
        with pytest.raises(ValueError, match="penetration_threshold must be >= 0"):
            BollingerBandsStrategy(penetration_threshold=-0.1)

    def test_price_below_lower_band_generates_entry_long(self) -> None:
        """Test that price below lower band generates ENTRY_LONG signal."""
        strategy = BollingerBandsStrategy(period=20, std_dev=2.0)

        # Create price data with strong downward move
        # Start stable, then sharp drop to break below lower band
        prices = [100.0] * 25 + [99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0, 91.0, 90.0]

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 0.5 for p in prices],
                "low": [p - 0.5 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("90.0"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        # Should generate ENTRY_LONG when price breaks below lower band
        assert signal.signal_type == SignalType.ENTRY_LONG
        assert signal.symbol == "BTC-USD"
        assert "lower_band" in signal.metadata
        assert signal.metadata["current_price"] < signal.metadata["lower_band"]

    def test_price_above_upper_band_generates_exit_long(self) -> None:
        """Test that price above upper band generates EXIT_LONG when in position."""
        strategy = BollingerBandsStrategy(period=20, std_dev=2.0)

        # Create price data with strong upward move
        # Start stable, then sharp rise to break above upper band
        prices = [100.0] * 25 + [
            101.0,
            102.0,
            103.0,
            104.0,
            105.0,
            106.0,
            107.0,
            108.0,
            109.0,
            110.0,
        ]

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 0.5 for p in prices],
                "low": [p - 0.5 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("110.0"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
            position_size=Decimal("1.0"),
            position_side=OrderSide.BUY,
            position_entry_price=Decimal("95.0"),
        )

        signal = strategy.generate_signal(context)

        # Should generate EXIT_LONG when price breaks above upper band
        assert signal.signal_type == SignalType.EXIT_LONG
        assert signal.symbol == "BTC-USD"
        assert "upper_band" in signal.metadata
        assert signal.metadata["current_price"] > signal.metadata["upper_band"]

    def test_price_within_bands_generates_hold(self) -> None:
        """Test that price within bands generates HOLD signal."""
        strategy = BollingerBandsStrategy(period=20, std_dev=2.0)

        # Create stable price data that stays within bands
        prices = [100.0 + (i % 3) for i in range(35)]

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 0.5 for p in prices],
                "low": [p - 0.5 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("101.0"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        # Should generate HOLD when price is within bands
        assert signal.signal_type == SignalType.HOLD
        assert signal.symbol == "BTC-USD"
        # Price should be between bands
        assert (
            signal.metadata["lower_band"]
            < signal.metadata["current_price"]
            < signal.metadata["upper_band"]
        )

    def test_price_below_band_with_position_generates_hold(self) -> None:
        """Test that price below band with existing position generates HOLD."""
        strategy = BollingerBandsStrategy(period=20, std_dev=2.0)

        # Create price data with downward move
        prices = [100.0] * 25 + list(range(99, 90, -1))

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 0.5 for p in prices],
                "low": [p - 0.5 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("90.0"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
            position_size=Decimal("1.0"),
            position_side=OrderSide.BUY,
            position_entry_price=Decimal("100.0"),
        )

        signal = strategy.generate_signal(context)

        # Should generate HOLD (already in position, can't enter again)
        assert signal.signal_type == SignalType.HOLD

    def test_price_above_band_without_position_generates_hold(self) -> None:
        """Test that price above band without position generates HOLD."""
        strategy = BollingerBandsStrategy(period=20, std_dev=2.0)

        # Create price data with upward move
        prices = [100.0] * 25 + list(range(101, 111))

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 0.5 for p in prices],
                "low": [p - 0.5 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("110.0"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        # Should generate HOLD (not in position, can't exit)
        assert signal.signal_type == SignalType.HOLD

    def test_signal_strength_strong_penetration(self) -> None:
        """Test signal strength for strong band penetration."""
        strategy = BollingerBandsStrategy(period=20, std_dev=2.0)

        # Create data with very strong downward breakout (> 1% penetration)
        prices = [100.0] * 25 + [99.0, 97.0, 95.0, 93.0, 91.0, 89.0, 87.0, 85.0, 83.0, 81.0]

        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 0.5 for p in prices],
                "low": [p - 0.5 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("81.0"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        # Strong penetration should result in STRONG signal strength
        if signal.signal_type == SignalType.ENTRY_LONG:
            # Calculate penetration percentage
            lower_band = signal.metadata["lower_band"]
            current_price = signal.metadata["current_price"]
            penetration_pct = (lower_band - current_price) / lower_band
            if penetration_pct > 0.01:  # > 1%
                assert signal.strength == SignalStrength.STRONG

    def test_insufficient_data_returns_hold(self) -> None:
        """Test that insufficient data returns HOLD signal."""
        strategy = BollingerBandsStrategy(period=20)

        # Only 10 candles - not enough (need 30)
        prices = [100 + i for i in range(10)]
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("109"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        assert signal.signal_type == SignalType.HOLD
        assert "reason" in signal.metadata
        assert signal.metadata["reason"] == "insufficient_candles"

    def test_empty_dataframe_returns_hold(self) -> None:
        """Test that empty DataFrame returns HOLD signal."""
        strategy = BollingerBandsStrategy(period=20)

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100"),
            timestamp=datetime.now(UTC),
            ohlcv=pd.DataFrame(),
        )

        signal = strategy.generate_signal(context)

        assert signal.signal_type == SignalType.HOLD

    def test_reset_is_noop(self) -> None:
        """Test that reset does nothing (strategy is stateless)."""
        strategy = BollingerBandsStrategy(period=20)

        # Reset should not raise an error
        strategy.reset()

        # Strategy should still work normally after reset
        prices = [100.0] * 35
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)
        assert signal.symbol == "BTC-USD"

    def test_metadata_contains_band_values(self) -> None:
        """Test that signal metadata contains band values."""
        strategy = BollingerBandsStrategy(period=20)

        # Create enough data
        prices = [100.0 + i * 0.1 for i in range(35)]
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 0.5 for p in prices],
                "low": [p - 0.5 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("103.5"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        assert "upper_band" in signal.metadata
        assert "middle_band" in signal.metadata
        assert "lower_band" in signal.metadata
        assert "band_width" in signal.metadata
        assert "current_price" in signal.metadata
        assert "period" in signal.metadata
        assert "std_dev" in signal.metadata
        assert isinstance(signal.metadata["upper_band"], float)
        assert (
            signal.metadata["lower_band"]
            < signal.metadata["middle_band"]
            < signal.metadata["upper_band"]
        )

    def test_custom_parameters(self) -> None:
        """Test strategy with custom parameters."""
        strategy = BollingerBandsStrategy(period=10, std_dev=3.0, penetration_threshold=0.005)

        assert strategy.name == "bollinger_bands_10_3"
        assert strategy.required_history == 20  # 10 + 10

        # Verify parameters are used correctly
        prices = [100.0] * 25
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        assert signal.metadata["period"] == 10
        assert signal.metadata["std_dev"] == 3.0

    def test_context_validation(self) -> None:
        """Test that context validation works correctly."""
        strategy = BollingerBandsStrategy(period=20)

        # Test with None ohlcv
        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100"),
            timestamp=datetime.now(UTC),
            ohlcv=None,  # type: ignore
        )

        signal = strategy.generate_signal(context)
        assert signal.signal_type == SignalType.HOLD
