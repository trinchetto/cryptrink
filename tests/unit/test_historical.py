"""Unit tests for historical data module."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from cryptrink.data.historical import (
    TIMEFRAME_SECONDS,
    HistoricalDataFetcher,
    OHLCVAggregator,
)
from cryptrink.exchange.base import OrderSide, Trade


def create_trade(
    trade_id: str,
    symbol: str,
    price: str,
    quantity: str,
    timestamp: datetime,
    side: OrderSide = OrderSide.BUY,
) -> Trade:
    """Helper to create a Trade object."""
    return Trade(
        id=trade_id,
        symbol=symbol,
        side=side,
        price=Decimal(price),
        quantity=Decimal(quantity),
        timestamp=timestamp,
    )


class TestTimeframeConstants:
    """Tests for timeframe constants."""

    def test_timeframe_seconds_contains_expected_values(self) -> None:
        """Test that TIMEFRAME_SECONDS has expected timeframes."""
        assert "1m" in TIMEFRAME_SECONDS
        assert "5m" in TIMEFRAME_SECONDS
        assert "15m" in TIMEFRAME_SECONDS
        assert "30m" in TIMEFRAME_SECONDS
        assert "1h" in TIMEFRAME_SECONDS
        assert "4h" in TIMEFRAME_SECONDS
        assert "1d" in TIMEFRAME_SECONDS

    def test_timeframe_values_are_correct(self) -> None:
        """Test that timeframe values are in seconds."""
        assert TIMEFRAME_SECONDS["1m"] == 60
        assert TIMEFRAME_SECONDS["5m"] == 300
        assert TIMEFRAME_SECONDS["15m"] == 900
        assert TIMEFRAME_SECONDS["30m"] == 1800
        assert TIMEFRAME_SECONDS["1h"] == 3600
        assert TIMEFRAME_SECONDS["4h"] == 14400
        assert TIMEFRAME_SECONDS["1d"] == 86400


class TestOHLCVAggregator:
    """Tests for OHLCV aggregator."""

    def test_aggregate_empty_trades(self) -> None:
        """Test aggregating an empty list of trades."""
        aggregator = OHLCVAggregator()
        result = aggregator.aggregate_trades([], "1m")
        assert result == []

    def test_aggregate_single_trade(self) -> None:
        """Test aggregating a single trade."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        trades = [
            create_trade("1", "BTC-USD", "42000.00", "1.5", timestamp),
        ]

        aggregator = OHLCVAggregator()
        result = aggregator.aggregate_trades(trades, "1m")

        assert len(result) == 1
        candle = result[0]
        assert candle["symbol"] == "BTC-USD"
        assert candle["timeframe"] == "1m"
        assert candle["timestamp"] == 1704110400000  # 2024-01-01 12:00:00 UTC in ms
        assert candle["open"] == Decimal("42000.00")
        assert candle["high"] == Decimal("42000.00")
        assert candle["low"] == Decimal("42000.00")
        assert candle["close"] == Decimal("42000.00")
        assert candle["volume"] == Decimal("1.5")

    def test_aggregate_multiple_trades_same_candle(self) -> None:
        """Test aggregating multiple trades in the same candle."""
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        trades = [
            create_trade("1", "BTC-USD", "42000.00", "1.0", base_time),
            create_trade("2", "BTC-USD", "42500.00", "0.5", base_time),
            create_trade("3", "BTC-USD", "41800.00", "2.0", base_time),
            create_trade("4", "BTC-USD", "42300.00", "1.5", base_time),
        ]

        aggregator = OHLCVAggregator()
        result = aggregator.aggregate_trades(trades, "1m")

        assert len(result) == 1
        candle = result[0]
        assert candle["open"] == Decimal("42000.00")  # First trade
        assert candle["high"] == Decimal("42500.00")  # Max price
        assert candle["low"] == Decimal("41800.00")  # Min price
        assert candle["close"] == Decimal("42300.00")  # Last trade
        assert candle["volume"] == Decimal("5.0")  # Sum of quantities

    def test_aggregate_trades_multiple_candles(self) -> None:
        """Test aggregating trades across multiple candles."""
        # Create trades in 3 different 1-minute candles
        trades = [
            # Candle 1: 12:00:00
            create_trade(
                "1", "BTC-USD", "42000.00", "1.0", datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
            ),
            create_trade(
                "2", "BTC-USD", "42100.00", "0.5", datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC)
            ),
            # Candle 2: 12:01:00
            create_trade(
                "3", "BTC-USD", "42200.00", "2.0", datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
            ),
            create_trade(
                "4", "BTC-USD", "42300.00", "1.0", datetime(2024, 1, 1, 12, 1, 45, tzinfo=UTC)
            ),
            # Candle 3: 12:02:00
            create_trade(
                "5", "BTC-USD", "42400.00", "0.8", datetime(2024, 1, 1, 12, 2, 15, tzinfo=UTC)
            ),
        ]

        aggregator = OHLCVAggregator()
        result = aggregator.aggregate_trades(trades, "1m")

        assert len(result) == 3

        # Check first candle
        assert result[0]["timestamp"] == 1704110400000  # 12:00:00
        assert result[0]["open"] == Decimal("42000.00")
        assert result[0]["close"] == Decimal("42100.00")
        assert result[0]["volume"] == Decimal("1.5")

        # Check second candle
        assert result[1]["timestamp"] == 1704110460000  # 12:01:00
        assert result[1]["open"] == Decimal("42200.00")
        assert result[1]["close"] == Decimal("42300.00")
        assert result[1]["volume"] == Decimal("3.0")

        # Check third candle
        assert result[2]["timestamp"] == 1704110520000  # 12:02:00
        assert result[2]["open"] == Decimal("42400.00")
        assert result[2]["close"] == Decimal("42400.00")
        assert result[2]["volume"] == Decimal("0.8")

    def test_aggregate_5m_timeframe(self) -> None:
        """Test aggregating trades into 5-minute candles."""
        trades = [
            # All within the same 5-minute window (12:00:00 - 12:04:59)
            create_trade(
                "1", "BTC-USD", "42000.00", "1.0", datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
            ),
            create_trade(
                "2", "BTC-USD", "42500.00", "1.0", datetime(2024, 1, 1, 12, 2, 0, tzinfo=UTC)
            ),
            create_trade(
                "3", "BTC-USD", "42300.00", "1.0", datetime(2024, 1, 1, 12, 4, 0, tzinfo=UTC)
            ),
            # Next 5-minute window (12:05:00 - 12:09:59)
            create_trade(
                "4", "BTC-USD", "42800.00", "1.0", datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC)
            ),
        ]

        aggregator = OHLCVAggregator()
        result = aggregator.aggregate_trades(trades, "5m")

        assert len(result) == 2

        # First 5-minute candle
        assert result[0]["timestamp"] == 1704110400000  # 12:00:00
        assert result[0]["open"] == Decimal("42000.00")
        assert result[0]["high"] == Decimal("42500.00")
        assert result[0]["low"] == Decimal("42000.00")
        assert result[0]["close"] == Decimal("42300.00")
        assert result[0]["volume"] == Decimal("3.0")

        # Second 5-minute candle
        assert result[1]["timestamp"] == 1704110700000  # 12:05:00
        assert result[1]["open"] == Decimal("42800.00")
        assert result[1]["close"] == Decimal("42800.00")
        assert result[1]["volume"] == Decimal("1.0")

    def test_aggregate_1h_timeframe(self) -> None:
        """Test aggregating trades into 1-hour candles."""
        trades = [
            create_trade(
                "1", "BTC-USD", "42000.00", "1.0", datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
            ),
            create_trade(
                "2", "BTC-USD", "42500.00", "1.0", datetime(2024, 1, 1, 12, 30, 0, tzinfo=UTC)
            ),
            create_trade(
                "3", "BTC-USD", "42300.00", "1.0", datetime(2024, 1, 1, 12, 59, 0, tzinfo=UTC)
            ),
            # Next hour
            create_trade(
                "4", "BTC-USD", "42800.00", "1.0", datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC)
            ),
        ]

        aggregator = OHLCVAggregator()
        result = aggregator.aggregate_trades(trades, "1h")

        assert len(result) == 2
        assert result[0]["timestamp"] == 1704110400000  # 12:00:00
        assert result[0]["volume"] == Decimal("3.0")
        assert result[1]["timestamp"] == 1704114000000  # 13:00:00
        assert result[1]["volume"] == Decimal("1.0")

    def test_aggregate_1d_timeframe(self) -> None:
        """Test aggregating trades into 1-day candles."""
        trades = [
            create_trade(
                "1", "BTC-USD", "42000.00", "1.0", datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
            ),
            create_trade(
                "2", "BTC-USD", "43000.00", "1.0", datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
            ),
            create_trade(
                "3", "BTC-USD", "42500.00", "1.0", datetime(2024, 1, 1, 23, 59, 0, tzinfo=UTC)
            ),
            # Next day
            create_trade(
                "4", "BTC-USD", "44000.00", "1.0", datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC)
            ),
        ]

        aggregator = OHLCVAggregator()
        result = aggregator.aggregate_trades(trades, "1d")

        assert len(result) == 2
        assert result[0]["timestamp"] == 1704067200000  # 2024-01-01 00:00:00
        assert result[0]["open"] == Decimal("42000.00")
        assert result[0]["high"] == Decimal("43000.00")
        assert result[0]["low"] == Decimal("42000.00")
        assert result[0]["close"] == Decimal("42500.00")
        assert result[0]["volume"] == Decimal("3.0")

    def test_aggregate_unsupported_timeframe(self) -> None:
        """Test that unsupported timeframe raises ValueError."""
        trades = [
            create_trade(
                "1", "BTC-USD", "42000.00", "1.0", datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
            ),
        ]

        aggregator = OHLCVAggregator()
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            aggregator.aggregate_trades(trades, "99m")

    def test_candles_sorted_by_timestamp(self) -> None:
        """Test that output candles are sorted by timestamp."""
        # Create trades in reverse chronological order
        trades = [
            create_trade(
                "3", "BTC-USD", "42400.00", "1.0", datetime(2024, 1, 1, 12, 2, 0, tzinfo=UTC)
            ),
            create_trade(
                "2", "BTC-USD", "42200.00", "1.0", datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
            ),
            create_trade(
                "1", "BTC-USD", "42000.00", "1.0", datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
            ),
        ]

        aggregator = OHLCVAggregator()
        result = aggregator.aggregate_trades(trades, "1m")

        # Should still be sorted ascending by timestamp
        assert len(result) == 3
        assert result[0]["timestamp"] < result[1]["timestamp"] < result[2]["timestamp"]


class TestHistoricalDataFetcher:
    """Tests for historical data fetcher."""

    @pytest.fixture
    def mock_exchange(self) -> Mock:
        """Create a mock exchange."""
        exchange = Mock()
        exchange.get_recent_trades = AsyncMock()
        return exchange

    @pytest.fixture
    def fetcher(self, mock_exchange: Mock) -> HistoricalDataFetcher:
        """Create a historical data fetcher with mock exchange."""
        return HistoricalDataFetcher(mock_exchange)

    async def test_fetch_recent_trades(
        self, fetcher: HistoricalDataFetcher, mock_exchange: Mock
    ) -> None:
        """Test fetching recent trades."""
        # Setup mock trades
        trades = [
            create_trade(
                "2", "BTC-USD", "42100.00", "1.0", datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
            ),
            create_trade(
                "1", "BTC-USD", "42000.00", "1.0", datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
            ),
            create_trade(
                "3", "BTC-USD", "42200.00", "1.0", datetime(2024, 1, 1, 12, 2, 0, tzinfo=UTC)
            ),
        ]
        mock_exchange.get_recent_trades.return_value = trades

        result = await fetcher.fetch_recent_trades("BTC-USD", limit=100)

        # Verify exchange was called correctly
        mock_exchange.get_recent_trades.assert_called_once_with("BTC-USD", limit=100)

        # Verify trades are sorted by timestamp
        assert len(result) == 3
        assert result[0].id == "1"  # Earliest
        assert result[1].id == "2"
        assert result[2].id == "3"  # Latest

    async def test_fetch_recent_trades_empty(
        self, fetcher: HistoricalDataFetcher, mock_exchange: Mock
    ) -> None:
        """Test fetching trades when none are available."""
        mock_exchange.get_recent_trades.return_value = []

        result = await fetcher.fetch_recent_trades("BTC-USD")

        assert result == []

    async def test_fetch_ohlcv(self, fetcher: HistoricalDataFetcher, mock_exchange: Mock) -> None:
        """Test fetching and aggregating OHLCV data."""
        # Setup mock trades
        trades = [
            create_trade(
                "1", "BTC-USD", "42000.00", "1.0", datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
            ),
            create_trade(
                "2", "BTC-USD", "42100.00", "1.0", datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC)
            ),
            create_trade(
                "3", "BTC-USD", "42200.00", "1.0", datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
            ),
        ]
        mock_exchange.get_recent_trades.return_value = trades

        result = await fetcher.fetch_ohlcv("BTC-USD", "1m", limit=100)

        # Should produce 2 candles (12:00 and 12:01)
        assert len(result) == 2
        assert result[0]["symbol"] == "BTC-USD"
        assert result[0]["timeframe"] == "1m"
        assert result[0]["volume"] == Decimal("2.0")  # 2 trades in first candle
        assert result[1]["volume"] == Decimal("1.0")  # 1 trade in second candle

    async def test_fetch_ohlcv_empty_trades(
        self, fetcher: HistoricalDataFetcher, mock_exchange: Mock
    ) -> None:
        """Test fetching OHLCV when no trades are available."""
        mock_exchange.get_recent_trades.return_value = []

        result = await fetcher.fetch_ohlcv("BTC-USD", "1m")

        assert result == []

    async def test_backfill_ohlcv_no_filter(
        self, fetcher: HistoricalDataFetcher, mock_exchange: Mock
    ) -> None:
        """Test backfilling OHLCV without time filter."""
        trades = [
            create_trade(
                "1", "BTC-USD", "42000.00", "1.0", datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
            ),
        ]
        mock_exchange.get_recent_trades.return_value = trades

        result = await fetcher.backfill_ohlcv("BTC-USD", "1m")

        assert len(result) == 1
        assert result[0]["symbol"] == "BTC-USD"

    async def test_backfill_ohlcv_with_time_range(
        self, fetcher: HistoricalDataFetcher, mock_exchange: Mock
    ) -> None:
        """Test backfilling OHLCV with time range filter."""
        # Create trades across 3 minutes
        trades = [
            create_trade(
                "1", "BTC-USD", "42000.00", "1.0", datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
            ),
            create_trade(
                "2", "BTC-USD", "42100.00", "1.0", datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
            ),
            create_trade(
                "3", "BTC-USD", "42200.00", "1.0", datetime(2024, 1, 1, 12, 2, 0, tzinfo=UTC)
            ),
        ]
        mock_exchange.get_recent_trades.return_value = trades

        # Fetch only middle minute
        start_time = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        end_time = datetime(2024, 1, 1, 12, 1, 59, tzinfo=UTC)

        result = await fetcher.backfill_ohlcv(
            "BTC-USD", "1m", start_time=start_time, end_time=end_time
        )

        # Should only get the middle candle
        assert len(result) == 1
        assert result[0]["timestamp"] == 1704110460000  # 12:01:00
