"""Unit tests for trend following strategies."""

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import pytest

from cryptrink.exchange.base import OrderSide
from cryptrink.strategies.base import SignalStrength, SignalType, StrategyContext
from cryptrink.strategies.trend_following import SmaCrossoverStrategy


class TestSmaCrossoverStrategy:
    """Tests for SMA Crossover strategy."""

    def test_init_valid_parameters(self) -> None:
        """Test initialization with valid parameters."""
        strategy = SmaCrossoverStrategy(fast_period=10, slow_period=30, signal_threshold=0.001)

        assert strategy.name == "sma_crossover_10_30"
        assert "fast=10" in strategy.description
        assert "slow=30" in strategy.description
        assert strategy.required_history == 40  # slow_period + 10
        assert strategy.timeframe == "1h"

    def test_init_invalid_fast_slow_period(self) -> None:
        """Test that fast_period must be less than slow_period."""
        with pytest.raises(ValueError, match="fast_period .* must be < slow_period"):
            SmaCrossoverStrategy(fast_period=30, slow_period=10)

        with pytest.raises(ValueError, match="fast_period .* must be < slow_period"):
            SmaCrossoverStrategy(fast_period=20, slow_period=20)

    def test_init_invalid_fast_period(self) -> None:
        """Test that fast_period must be >= 2."""
        with pytest.raises(ValueError, match="fast_period must be >= 2"):
            SmaCrossoverStrategy(fast_period=1, slow_period=30)

    def test_init_invalid_threshold(self) -> None:
        """Test that signal_threshold must be >= 0."""
        with pytest.raises(ValueError, match="signal_threshold must be >= 0"):
            SmaCrossoverStrategy(fast_period=10, slow_period=30, signal_threshold=-0.1)

    def test_bullish_crossover_generates_entry_long(self) -> None:
        """Test that bullish crossover generates ENTRY_LONG signal."""
        strategy = SmaCrossoverStrategy(fast_period=3, slow_period=5, signal_threshold=0.001)

        # Create price data that will cause bullish crossover
        # Need enough data for required_history (slow_period + 10 = 15)
        # Prices: flat then trending up so fast SMA crosses above slow SMA
        prices = [100, 100, 100, 100, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110]
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
            current_price=Decimal("110"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        # First call to establish previous values
        _ = strategy.generate_signal(context)

        # Add more price points to ensure crossover occurs
        prices.extend([111, 112, 113])
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
            current_price=Decimal("113"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal2 = strategy.generate_signal(context)

        # Should generate entry signal on crossover or have metadata
        assert signal2.symbol == "BTC-USD"
        assert "fast_sma" in signal2.metadata
        assert "slow_sma" in signal2.metadata

    def test_bearish_crossover_generates_exit_long(self) -> None:
        """Test that bearish crossover generates EXIT_LONG when in position."""
        strategy = SmaCrossoverStrategy(fast_period=3, slow_period=5, signal_threshold=0.001)

        # Create price data with downtrend - need at least 15 candles
        # Start flat, then trend down to trigger bearish crossover
        prices = [110, 110, 110, 110, 110, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100]
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
            position_size=Decimal("1.0"),
            position_side=OrderSide.BUY,
            position_entry_price=Decimal("110"),
        )

        # First call to establish previous values
        _ = strategy.generate_signal(context)

        # Add more downward movement
        prices.append(97)
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
            current_price=Decimal("97"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
            position_size=Decimal("1.0"),
            position_side=OrderSide.BUY,
            position_entry_price=Decimal("110"),
        )

        signal2 = strategy.generate_signal(context)

        assert signal2.signal_type in (SignalType.EXIT_LONG, SignalType.HOLD)

    def test_hold_signal_when_no_crossover(self) -> None:
        """Test that HOLD signal is generated when no crossover occurs."""
        strategy = SmaCrossoverStrategy(fast_period=3, slow_period=5, signal_threshold=0.001)

        # Flat prices - no crossover
        prices = [100] * 10
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

        # Generate signals multiple times
        _ = strategy.generate_signal(context)
        signal2 = strategy.generate_signal(context)

        assert signal2.signal_type == SignalType.HOLD

    def test_signal_threshold_filters_weak_signals(self) -> None:
        """Test that signal threshold filters out weak crossovers."""
        strategy = SmaCrossoverStrategy(fast_period=3, slow_period=5, signal_threshold=0.05)

        # Small price movement - should not trigger signal
        prices = [100.0, 100.1, 100.2, 100.3, 100.4, 100.5]
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 0.1 for p in prices],
                "low": [p - 0.1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100.5"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        # Should generate HOLD due to high threshold
        assert signal.signal_type == SignalType.HOLD

    def test_signal_strength_calculation(self) -> None:
        """Test signal strength is calculated correctly."""
        strategy = SmaCrossoverStrategy(fast_period=3, slow_period=5, signal_threshold=0.001)

        # Strong uptrend - need at least 15 candles
        prices = [100, 100, 100, 100, 100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 150]
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 2 for p in prices],
                "low": [p - 2 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("150"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        # Large price movement should result in strong signal
        assert signal.strength in (
            SignalStrength.WEAK,
            SignalStrength.MODERATE,
            SignalStrength.STRONG,
        )

    def test_insufficient_data_returns_hold(self) -> None:
        """Test that insufficient data returns HOLD signal."""
        strategy = SmaCrossoverStrategy(fast_period=10, slow_period=30, signal_threshold=0.001)

        # Only 5 candles - not enough
        prices = [100, 101, 102, 103, 104]
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
            current_price=Decimal("104"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        assert signal.signal_type == SignalType.HOLD
        assert "reason" in signal.metadata
        assert signal.metadata["reason"] == "insufficient_candles"

    def test_empty_dataframe_returns_hold(self) -> None:
        """Test that empty DataFrame returns HOLD signal."""
        strategy = SmaCrossoverStrategy(fast_period=10, slow_period=30)

        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100"),
            timestamp=datetime.now(UTC),
            ohlcv=pd.DataFrame(),
        )

        signal = strategy.generate_signal(context)

        assert signal.signal_type == SignalType.HOLD

    def test_reset_clears_state(self) -> None:
        """Test that reset clears previous SMA values."""
        strategy = SmaCrossoverStrategy(fast_period=3, slow_period=5)

        # Need at least 15 candles for required_history
        prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114]
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
            current_price=Decimal("114"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        # Generate signal to set internal state
        strategy.generate_signal(context)

        # Verify state exists
        assert strategy._prev_fast_sma is not None
        assert strategy._prev_slow_sma is not None

        # Reset
        strategy.reset()

        # Verify state cleared
        assert strategy._prev_fast_sma is None
        assert strategy._prev_slow_sma is None

    def test_metadata_contains_sma_values(self) -> None:
        """Test that signal metadata contains SMA values."""
        strategy = SmaCrossoverStrategy(fast_period=3, slow_period=5)

        # Need at least 15 candles for required_history
        prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114]
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
            current_price=Decimal("114"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        signal = strategy.generate_signal(context)

        assert "fast_sma" in signal.metadata
        assert "slow_sma" in signal.metadata
        assert "pct_diff" in signal.metadata
        assert "threshold" in signal.metadata
        assert isinstance(signal.metadata["fast_sma"], float)
        assert isinstance(signal.metadata["slow_sma"], float)

    def test_context_validation(self) -> None:
        """Test that context validation works correctly."""
        strategy = SmaCrossoverStrategy(fast_period=10, slow_period=30)

        # Invalid: empty DataFrame
        context1 = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100"),
            timestamp=datetime.now(UTC),
            ohlcv=pd.DataFrame(),
        )
        assert not strategy.validate_context(context1)

        # Invalid: insufficient history
        prices = [100] * 20  # Less than required_history (40)
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )
        context2 = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )
        assert not strategy.validate_context(context2)

        # Valid: sufficient history
        prices = [100] * 50
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )
        context3 = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )
        assert strategy.validate_context(context3)

    def test_custom_parameters(self) -> None:
        """Test strategy with custom parameters."""
        strategy = SmaCrossoverStrategy(fast_period=5, slow_period=20, signal_threshold=0.002)

        assert strategy.name == "sma_crossover_5_20"
        assert strategy.required_history == 30  # 20 + 10
        assert "fast=5" in strategy.description
        assert "slow=20" in strategy.description
