"""Unit tests for technical indicators module."""

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from cryptrink.data.indicators import Indicators, ohlcv_to_dataframe


class TestSMA:
    """Tests for Simple Moving Average."""

    def test_sma_basic(self) -> None:
        """Test basic SMA calculation."""
        prices = pd.Series([10, 20, 30, 40, 50])
        result = Indicators.sma(prices, period=3)

        # First 2 values should be NaN, then moving averages
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        assert result.iloc[2] == 20.0  # (10 + 20 + 30) / 3
        assert result.iloc[3] == 30.0  # (20 + 30 + 40) / 3
        assert result.iloc[4] == 40.0  # (30 + 40 + 50) / 3

    def test_sma_period_1(self) -> None:
        """Test SMA with period 1 (returns same values)."""
        prices = pd.Series([10.0, 20.0, 30.0])
        result = Indicators.sma(prices, period=1)

        pd.testing.assert_series_equal(result, prices, check_names=False)

    def test_sma_invalid_period(self) -> None:
        """Test SMA with invalid period."""
        prices = pd.Series([10, 20, 30])

        with pytest.raises(ValueError, match="Period must be >= 1"):
            Indicators.sma(prices, period=0)

    def test_sma_empty_series(self) -> None:
        """Test SMA with empty series."""
        prices = pd.Series([], dtype=float)
        result = Indicators.sma(prices, period=3)

        assert len(result) == 0


class TestEMA:
    """Tests for Exponential Moving Average."""

    def test_ema_basic(self) -> None:
        """Test basic EMA calculation."""
        prices = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        result = Indicators.ema(prices, period=3)

        # EMA should have all values (no NaN at start)
        assert len(result) == 5
        assert not result.isna().any()

        # EMA should be more responsive than SMA
        # Last value should be closer to recent prices
        assert result.iloc[-1] > 30.0  # Greater than simple average

    def test_ema_period_1(self) -> None:
        """Test EMA with period 1 (returns same values)."""
        prices = pd.Series([10.0, 20.0, 30.0])
        result = Indicators.ema(prices, period=1)

        pd.testing.assert_series_equal(result, prices, check_names=False)

    def test_ema_invalid_period(self) -> None:
        """Test EMA with invalid period."""
        prices = pd.Series([10, 20, 30])

        with pytest.raises(ValueError, match="Period must be >= 1"):
            Indicators.ema(prices, period=0)


class TestRSI:
    """Tests for Relative Strength Index."""

    def test_rsi_basic(self) -> None:
        """Test basic RSI calculation."""
        # Create price series with clear up and down moves
        prices = pd.Series(
            [100, 105, 110, 108, 112, 115, 113, 118, 120, 117, 122, 125, 123, 128, 130]
        )
        result = Indicators.rsi(prices, period=14)

        # First 14 values should be NaN (need period+1 for first RSI)
        assert result.iloc[13] > 0
        assert result.iloc[14] > 0

        # RSI should be between 0 and 100
        valid_rsi = result.dropna()
        assert (valid_rsi >= 0).all()
        assert (valid_rsi <= 100).all()

    def test_rsi_overbought(self) -> None:
        """Test RSI with strong uptrend (should be high)."""
        # Create strongly increasing prices
        prices = pd.Series(list(range(100, 130)))
        result = Indicators.rsi(prices, period=14)

        # RSI should be high (>70) in strong uptrend
        assert result.iloc[-1] > 70

    def test_rsi_oversold(self) -> None:
        """Test RSI with strong downtrend (should be low)."""
        # Create strongly decreasing prices
        prices = pd.Series(list(range(130, 100, -1)))
        result = Indicators.rsi(prices, period=14)

        # RSI should be low (<30) in strong downtrend
        assert result.iloc[-1] < 30

    def test_rsi_invalid_period(self) -> None:
        """Test RSI with invalid period."""
        prices = pd.Series([100, 105, 110])

        with pytest.raises(ValueError, match="Period must be >= 1"):
            Indicators.rsi(prices, period=0)


class TestBollingerBands:
    """Tests for Bollinger Bands."""

    def test_bollinger_bands_basic(self) -> None:
        """Test basic Bollinger Bands calculation."""
        prices = pd.Series(
            [100, 102, 101, 103, 105, 104, 106, 108, 107, 109, 110, 112, 111, 113, 115] * 2
        )
        upper, middle, lower = Indicators.bollinger_bands(prices, period=20, std_dev=2.0)

        # All bands should have same length
        assert len(upper) == len(middle) == len(lower)

        # Check valid values (after period)
        valid_idx = 19  # First valid index after 20-period
        assert upper.iloc[valid_idx] > middle.iloc[valid_idx]
        assert middle.iloc[valid_idx] > lower.iloc[valid_idx]

        # Upper and lower should be equidistant from middle
        upper_dist = upper.iloc[valid_idx] - middle.iloc[valid_idx]
        lower_dist = middle.iloc[valid_idx] - lower.iloc[valid_idx]
        assert abs(upper_dist - lower_dist) < 0.0001

    def test_bollinger_bands_std_dev(self) -> None:
        """Test Bollinger Bands with different standard deviations."""
        prices = pd.Series(
            [100, 102, 101, 103, 105, 104, 106, 108, 107, 109, 110, 112, 111, 113, 115] * 2
        )

        upper1, middle1, lower1 = Indicators.bollinger_bands(prices, period=20, std_dev=1.0)
        upper2, middle2, lower2 = Indicators.bollinger_bands(prices, period=20, std_dev=2.0)

        valid_idx = 19

        # Middle band should be same regardless of std_dev
        assert middle1.iloc[valid_idx] == middle2.iloc[valid_idx]

        # Wider std_dev should create wider bands
        band_width_1 = upper1.iloc[valid_idx] - lower1.iloc[valid_idx]
        band_width_2 = upper2.iloc[valid_idx] - lower2.iloc[valid_idx]
        assert band_width_2 > band_width_1

    def test_bollinger_bands_invalid_params(self) -> None:
        """Test Bollinger Bands with invalid parameters."""
        prices = pd.Series([100, 102, 101])

        with pytest.raises(ValueError, match="Period must be >= 1"):
            Indicators.bollinger_bands(prices, period=0, std_dev=2.0)

        with pytest.raises(ValueError, match="Standard deviation must be >= 0"):
            Indicators.bollinger_bands(prices, period=20, std_dev=-1.0)


class TestMACD:
    """Tests for MACD."""

    def test_macd_basic(self) -> None:
        """Test basic MACD calculation."""
        # Create trending prices
        prices = pd.Series([100 + i * 0.5 for i in range(50)])
        macd_line, signal_line, histogram = Indicators.macd(
            prices, fast_period=12, slow_period=26, signal_period=9
        )

        # All components should have same length
        assert len(macd_line) == len(signal_line) == len(histogram)

        # Histogram should be difference between MACD and signal
        assert abs(histogram.iloc[-1] - (macd_line.iloc[-1] - signal_line.iloc[-1])) < 0.0001

    def test_macd_uptrend(self) -> None:
        """Test MACD in uptrend (should be positive)."""
        # Strong uptrend
        prices = pd.Series([100 + i * 2 for i in range(50)])
        macd_line, _signal_line, _histogram = Indicators.macd(prices)

        # In strong uptrend, MACD should be positive
        assert macd_line.iloc[-1] > 0

    def test_macd_downtrend(self) -> None:
        """Test MACD in downtrend (should be negative)."""
        # Strong downtrend
        prices = pd.Series([200 - i * 2 for i in range(50)])
        macd_line, _signal_line, _histogram = Indicators.macd(prices)

        # In strong downtrend, MACD should be negative
        assert macd_line.iloc[-1] < 0

    def test_macd_invalid_periods(self) -> None:
        """Test MACD with invalid periods."""
        prices = pd.Series([100, 102, 101])

        with pytest.raises(ValueError, match="Fast period must be >= 1"):
            Indicators.macd(prices, fast_period=0, slow_period=26, signal_period=9)

        with pytest.raises(ValueError, match="Slow period must be >= 1"):
            Indicators.macd(prices, fast_period=12, slow_period=0, signal_period=9)

        with pytest.raises(ValueError, match="Signal period must be >= 1"):
            Indicators.macd(prices, fast_period=12, slow_period=26, signal_period=0)

        with pytest.raises(ValueError, match=r"Fast period .* must be < slow period"):
            Indicators.macd(prices, fast_period=26, slow_period=12, signal_period=9)


class TestATR:
    """Tests for Average True Range."""

    def test_atr_basic(self) -> None:
        """Test basic ATR calculation."""
        high = pd.Series(
            [105, 108, 107, 110, 112, 111, 113, 115, 114, 116, 118, 117, 119, 121, 120]
        )
        low = pd.Series([95, 98, 97, 100, 102, 101, 103, 105, 104, 106, 108, 107, 109, 111, 110])
        close = pd.Series(
            [100, 103, 102, 105, 107, 106, 108, 110, 109, 111, 113, 112, 114, 116, 115]
        )

        result = Indicators.atr(high, low, close, period=14)

        # First value should be NaN, then valid ATR values
        assert pd.isna(result.iloc[0])
        assert result.iloc[14] > 0  # ATR should be positive

    def test_atr_increasing_volatility(self) -> None:
        """Test ATR with increasing volatility."""
        # Create data with increasing range
        high = pd.Series([100 + i + i * 0.5 for i in range(30)])
        low = pd.Series([100 + i - i * 0.5 for i in range(30)])
        close = pd.Series([100 + i for i in range(30)])

        result = Indicators.atr(high, low, close, period=14)

        # ATR should increase with increasing volatility
        valid_results = result.dropna()
        assert valid_results.iloc[-1] > valid_results.iloc[0]

    def test_atr_invalid_params(self) -> None:
        """Test ATR with invalid parameters."""
        high = pd.Series([105, 108, 107])
        low = pd.Series([95, 98, 97])
        close = pd.Series([100, 103, 102])

        with pytest.raises(ValueError, match="Period must be >= 1"):
            Indicators.atr(high, low, close, period=0)

        # Mismatched lengths
        with pytest.raises(ValueError, match="same length"):
            Indicators.atr(high, low, pd.Series([100, 103]), period=14)


class TestOHLCVToDataFrame:
    """Tests for OHLCV to DataFrame conversion."""

    def test_conversion_basic(self) -> None:
        """Test basic OHLCV to DataFrame conversion."""
        ohlcv_data = [
            {
                "timestamp": 1704067200000,  # 2024-01-01 00:00:00 UTC
                "open": Decimal("100.0"),
                "high": Decimal("105.0"),
                "low": Decimal("95.0"),
                "close": Decimal("102.0"),
                "volume": Decimal("1000.0"),
                "symbol": "BTC-USD",
                "timeframe": "1h",
            },
            {
                "timestamp": 1704070800000,  # 2024-01-01 01:00:00 UTC
                "open": Decimal("102.0"),
                "high": Decimal("108.0"),
                "low": Decimal("98.0"),
                "close": Decimal("105.0"),
                "volume": Decimal("1200.0"),
                "symbol": "BTC-USD",
                "timeframe": "1h",
            },
        ]

        df = ohlcv_to_dataframe(ohlcv_data)

        # Check shape
        assert len(df) == 2
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

        # Check index is datetime
        assert isinstance(df.index, pd.DatetimeIndex)

        # Check values are floats
        assert df["open"].dtype == np.float64
        assert df["high"].iloc[0] == 105.0
        assert df["close"].iloc[1] == 105.0

    def test_conversion_empty(self) -> None:
        """Test conversion with empty data."""
        df = ohlcv_to_dataframe([])

        assert len(df) == 0
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_conversion_preserves_order(self) -> None:
        """Test that conversion preserves time order."""
        ohlcv_data = [
            {
                "timestamp": 1704070800000,
                "open": 102.0,
                "high": 108.0,
                "low": 98.0,
                "close": 105.0,
                "volume": 1200.0,
            },
            {
                "timestamp": 1704067200000,
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 102.0,
                "volume": 1000.0,
            },
            {
                "timestamp": 1704074400000,
                "open": 105.0,
                "high": 110.0,
                "low": 100.0,
                "close": 108.0,
                "volume": 1500.0,
            },
        ]

        df = ohlcv_to_dataframe(ohlcv_data)

        # Should preserve original order (not automatically sort)
        assert df.index[0].timestamp() == 1704070800
        assert df.index[1].timestamp() == 1704067200
        assert df.index[2].timestamp() == 1704074400
