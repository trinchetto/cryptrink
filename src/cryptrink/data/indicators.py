"""Technical indicators for price analysis.

This module provides common technical indicators calculated from OHLCV data.
All indicators work with pandas Series/DataFrames for efficient computation.
"""

from decimal import Decimal
from typing import Any

import pandas as pd


class Indicators:
    """Technical indicators calculator.

    Provides static methods for calculating various technical indicators
    from OHLCV data. All methods accept pandas Series and return pandas Series.
    """

    @staticmethod
    def sma(prices: pd.Series, period: int) -> pd.Series:
        """Calculate Simple Moving Average (SMA).

        Args:
            prices: Price series (typically close prices).
            period: Number of periods for the average.

        Returns:
            Series with SMA values (NaN for first period-1 values).

        Raises:
            ValueError: If period is less than 1.
        """
        if period < 1:
            raise ValueError(f"Period must be >= 1, got {period}")

        return prices.rolling(window=period).mean()

    @staticmethod
    def ema(prices: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average (EMA).

        Args:
            prices: Price series (typically close prices).
            period: Number of periods for the average.

        Returns:
            Series with EMA values.

        Raises:
            ValueError: If period is less than 1.
        """
        if period < 1:
            raise ValueError(f"Period must be >= 1, got {period}")

        return prices.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index (RSI).

        Args:
            prices: Price series (typically close prices).
            period: Number of periods for RSI calculation (default: 14).

        Returns:
            Series with RSI values (0-100 range).

        Raises:
            ValueError: If period is less than 1.
        """
        if period < 1:
            raise ValueError(f"Period must be >= 1, got {period}")

        # Calculate price changes
        delta = prices.diff()

        # Separate gains and losses
        gains = delta.where(delta > 0, 0.0)
        losses = -delta.where(delta < 0, 0.0)

        # Calculate average gains and losses
        avg_gains = gains.rolling(window=period).mean()
        avg_losses = losses.rolling(window=period).mean()

        # Calculate RS and RSI
        rs = avg_gains / avg_losses
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @staticmethod
    def bollinger_bands(
        prices: pd.Series, period: int = 20, std_dev: float = 2.0
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Bollinger Bands.

        Args:
            prices: Price series (typically close prices).
            period: Number of periods for the moving average (default: 20).
            std_dev: Number of standard deviations for bands (default: 2.0).

        Returns:
            Tuple of (upper_band, middle_band, lower_band) as pandas Series.

        Raises:
            ValueError: If period is less than 1 or std_dev is negative.
        """
        if period < 1:
            raise ValueError(f"Period must be >= 1, got {period}")
        if std_dev < 0:
            raise ValueError(f"Standard deviation must be >= 0, got {std_dev}")

        # Middle band is SMA
        middle_band = prices.rolling(window=period).mean()

        # Calculate standard deviation
        rolling_std = prices.rolling(window=period).std()

        # Upper and lower bands
        upper_band = middle_band + (rolling_std * std_dev)
        lower_band = middle_band - (rolling_std * std_dev)

        return upper_band, middle_band, lower_band

    @staticmethod
    def macd(
        prices: pd.Series,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate MACD (Moving Average Convergence Divergence).

        Args:
            prices: Price series (typically close prices).
            fast_period: Period for fast EMA (default: 12).
            slow_period: Period for slow EMA (default: 26).
            signal_period: Period for signal line EMA (default: 9).

        Returns:
            Tuple of (macd_line, signal_line, histogram) as pandas Series.

        Raises:
            ValueError: If any period is less than 1 or fast >= slow.
        """
        if fast_period < 1:
            raise ValueError(f"Fast period must be >= 1, got {fast_period}")
        if slow_period < 1:
            raise ValueError(f"Slow period must be >= 1, got {slow_period}")
        if signal_period < 1:
            raise ValueError(f"Signal period must be >= 1, got {signal_period}")
        if fast_period >= slow_period:
            raise ValueError(f"Fast period ({fast_period}) must be < slow period ({slow_period})")

        # Calculate EMAs
        fast_ema = prices.ewm(span=fast_period, adjust=False).mean()
        slow_ema = prices.ewm(span=slow_period, adjust=False).mean()

        # MACD line is the difference
        macd_line = fast_ema - slow_ema

        # Signal line is EMA of MACD line
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()

        # Histogram is the difference between MACD and signal
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Average True Range (ATR).

        Args:
            high: High price series.
            low: Low price series.
            close: Close price series.
            period: Number of periods for ATR calculation (default: 14).

        Returns:
            Series with ATR values.

        Raises:
            ValueError: If period is less than 1 or series have different lengths.
        """
        if period < 1:
            raise ValueError(f"Period must be >= 1, got {period}")
        if len(high) != len(low) or len(high) != len(close):
            raise ValueError("High, low, and close series must have same length")

        # Calculate True Range components
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # ATR is the moving average of True Range
        atr = true_range.rolling(window=period).mean()

        return atr


def ohlcv_to_dataframe(ohlcv_data: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert OHLCV data dictionaries to a pandas DataFrame.

    Args:
        ohlcv_data: List of OHLCV dictionaries with keys:
            timestamp, open, high, low, close, volume.

    Returns:
        DataFrame with datetime index and OHLCV columns as float64.
        Decimal values are converted to float for pandas compatibility.
    """
    if not ohlcv_data:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    # Convert to DataFrame
    df = pd.DataFrame(ohlcv_data)

    # Convert timestamp to datetime index
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("datetime", inplace=True)

    # Convert Decimal to float for pandas operations
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: float(x) if isinstance(x, Decimal) else x)

    # Drop timestamp and symbol/timeframe columns if present
    df = df[["open", "high", "low", "close", "volume"]]

    return df
