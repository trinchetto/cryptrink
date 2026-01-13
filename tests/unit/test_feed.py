"""Unit tests for data feed module."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from cryptrink.data.feed import (
    BaseDataFeed,
    HistoricalDataFeed,
    HybridDataFeed,
    LiveDataFeed,
)
from cryptrink.data.storage import OHLCV


class TestBaseDataFeed:
    """Tests for BaseDataFeed abstract class."""

    def test_cannot_instantiate_abstract_class(self) -> None:
        """Test that BaseDataFeed cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseDataFeed()  # type: ignore


class TestLiveDataFeed:
    """Tests for LiveDataFeed."""

    @pytest.fixture
    def mock_exchange(self) -> Mock:
        """Create a mock exchange."""
        exchange = Mock()
        exchange.get_recent_trades = AsyncMock()
        return exchange

    @pytest.fixture
    def mock_repository(self) -> Mock:
        """Create a mock repository."""
        repository = Mock()
        repository.save_batch = AsyncMock(return_value=3)
        return repository

    async def test_get_ohlcv_basic(self, mock_exchange: Mock) -> None:
        """Test basic OHLCV fetching from live exchange."""
        # Mock trades that will be aggregated
        from cryptrink.exchange.base import OrderSide, Trade

        trades = [
            Trade(
                id="1",
                symbol="BTC-USD",
                side=OrderSide.BUY,
                price=Decimal("42000"),
                quantity=Decimal("1.0"),
                timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ),
            Trade(
                id="2",
                symbol="BTC-USD",
                side=OrderSide.BUY,
                price=Decimal("42100"),
                quantity=Decimal("0.5"),
                timestamp=datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC),
            ),
        ]
        mock_exchange.get_recent_trades.return_value = trades

        feed = LiveDataFeed(mock_exchange, store_data=False)
        result = await feed.get_ohlcv("BTC-USD", "1m", limit=10)

        assert len(result) > 0
        assert result[0]["symbol"] == "BTC-USD"
        assert result[0]["timeframe"] == "1m"

    async def test_get_ohlcv_stores_data(self, mock_exchange: Mock, mock_repository: Mock) -> None:
        """Test that live feed stores data when enabled."""
        from cryptrink.exchange.base import OrderSide, Trade

        trades = [
            Trade(
                id="1",
                symbol="BTC-USD",
                side=OrderSide.BUY,
                price=Decimal("42000"),
                quantity=Decimal("1.0"),
                timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ),
        ]
        mock_exchange.get_recent_trades.return_value = trades

        feed = LiveDataFeed(mock_exchange, mock_repository, store_data=True)
        await feed.get_ohlcv("BTC-USD", "1m", limit=10)

        # Verify save_batch was called
        mock_repository.save_batch.assert_called_once()

    async def test_get_ohlcv_no_store(self, mock_exchange: Mock, mock_repository: Mock) -> None:
        """Test that live feed doesn't store data when disabled."""
        from cryptrink.exchange.base import OrderSide, Trade

        trades = [
            Trade(
                id="1",
                symbol="BTC-USD",
                side=OrderSide.BUY,
                price=Decimal("42000"),
                quantity=Decimal("1.0"),
                timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ),
        ]
        mock_exchange.get_recent_trades.return_value = trades

        feed = LiveDataFeed(mock_exchange, mock_repository, store_data=False)
        await feed.get_ohlcv("BTC-USD", "1m", limit=10)

        # Verify save_batch was NOT called
        mock_repository.save_batch.assert_not_called()

    async def test_get_ohlcv_dataframe(self, mock_exchange: Mock) -> None:
        """Test getting OHLCV data as DataFrame."""
        from cryptrink.exchange.base import OrderSide, Trade

        trades = [
            Trade(
                id="1",
                symbol="BTC-USD",
                side=OrderSide.BUY,
                price=Decimal("42000"),
                quantity=Decimal("1.0"),
                timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ),
        ]
        mock_exchange.get_recent_trades.return_value = trades

        feed = LiveDataFeed(mock_exchange, store_data=False)
        df = await feed.get_ohlcv_dataframe("BTC-USD", "1m", limit=10)

        assert len(df) > 0
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]


class TestHistoricalDataFeed:
    """Tests for HistoricalDataFeed."""

    @pytest.fixture
    def mock_repository(self) -> Mock:
        """Create a mock repository."""
        repository = Mock()
        repository.get = AsyncMock()
        return repository

    async def test_get_ohlcv_basic(self, mock_repository: Mock) -> None:
        """Test basic OHLCV fetching from repository."""
        # Mock OHLCV records
        mock_records = [
            OHLCV(
                symbol="BTC-USD",
                timeframe="1h",
                timestamp=1704067200000,
                open="42000.00",
                high="42500.00",
                low="41800.00",
                close="42300.00",
                volume="100.00",
            ),
            OHLCV(
                symbol="BTC-USD",
                timeframe="1h",
                timestamp=1704070800000,
                open="42300.00",
                high="42800.00",
                low="42100.00",
                close="42600.00",
                volume="120.00",
            ),
        ]
        mock_repository.get.return_value = mock_records

        feed = HistoricalDataFeed(mock_repository)
        result = await feed.get_ohlcv("BTC-USD", "1h", limit=10)

        assert len(result) == 2
        assert result[0]["symbol"] == "BTC-USD"
        assert result[0]["timeframe"] == "1h"
        assert result[0]["open"] == Decimal("42000.00")
        assert result[0]["timestamp"] == 1704067200000

    async def test_get_ohlcv_with_time_filter(self, mock_repository: Mock) -> None:
        """Test fetching with time filter."""
        mock_repository.get.return_value = []

        feed = HistoricalDataFeed(mock_repository)
        start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        end_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC)

        await feed.get_ohlcv("BTC-USD", "1h", limit=10, start_time=start_time, end_time=end_time)

        # Verify repository was called with correct timestamps
        mock_repository.get.assert_called_once()
        call_args = mock_repository.get.call_args
        assert call_args[1]["start_time"] == 1704110400000  # 12:00:00 UTC
        assert call_args[1]["end_time"] == 1704114000000  # 13:00:00 UTC

    async def test_get_ohlcv_empty_result(self, mock_repository: Mock) -> None:
        """Test fetching when no data exists."""
        mock_repository.get.return_value = []

        feed = HistoricalDataFeed(mock_repository)
        result = await feed.get_ohlcv("BTC-USD", "1h", limit=10)

        assert len(result) == 0


class TestHybridDataFeed:
    """Tests for HybridDataFeed."""

    @pytest.fixture
    def mock_exchange(self) -> Mock:
        """Create a mock exchange."""
        exchange = Mock()
        exchange.get_recent_trades = AsyncMock()
        return exchange

    @pytest.fixture
    def mock_repository(self) -> Mock:
        """Create a mock repository."""
        repository = Mock()
        repository.get = AsyncMock()
        repository.save_batch = AsyncMock()
        return repository

    async def test_get_ohlcv_uses_historical_when_sufficient(
        self, mock_exchange: Mock, mock_repository: Mock
    ) -> None:
        """Test that hybrid feed uses historical data when sufficient."""
        # Mock sufficient historical data
        mock_records = [
            OHLCV(
                symbol="BTC-USD",
                timeframe="1h",
                timestamp=1704067200000 + i * 3600000,
                open="42000.00",
                high="42500.00",
                low="41800.00",
                close="42300.00",
                volume="100.00",
            )
            for i in range(10)
        ]
        mock_repository.get.return_value = mock_records

        feed = HybridDataFeed(mock_exchange, mock_repository)
        result = await feed.get_ohlcv("BTC-USD", "1h", limit=5)

        # Should have historical data
        assert len(result) >= 5

        # Exchange should not have been called
        mock_exchange.get_recent_trades.assert_not_called()

    async def test_get_ohlcv_falls_back_to_live(
        self, mock_exchange: Mock, mock_repository: Mock
    ) -> None:
        """Test that hybrid feed falls back to live when historical insufficient."""
        from cryptrink.exchange.base import OrderSide, Trade

        # Mock insufficient historical data
        mock_repository.get.return_value = []

        # Mock live trades
        trades = [
            Trade(
                id=str(i),
                symbol="BTC-USD",
                side=OrderSide.BUY,
                price=Decimal("42000") + Decimal(i * 100),
                quantity=Decimal("1.0"),
                timestamp=datetime(2024, 1, 1, 12, i, 0, tzinfo=UTC),
            )
            for i in range(10)
        ]
        mock_exchange.get_recent_trades.return_value = trades

        feed = HybridDataFeed(mock_exchange, mock_repository)
        result = await feed.get_ohlcv("BTC-USD", "1m", limit=5)

        # Should have live data
        assert len(result) > 0

        # Exchange should have been called
        mock_exchange.get_recent_trades.assert_called()

    async def test_get_ohlcv_merges_historical_and_live(
        self, mock_exchange: Mock, mock_repository: Mock
    ) -> None:
        """Test that hybrid feed merges historical and live data."""
        from cryptrink.exchange.base import OrderSide, Trade

        # Mock some historical data (but not enough)
        mock_records = [
            OHLCV(
                symbol="BTC-USD",
                timeframe="1m",
                timestamp=1704110400000 + i * 60000,
                open="42000.00",
                high="42500.00",
                low="41800.00",
                close="42300.00",
                volume="100.00",
            )
            for i in range(3)
        ]
        mock_repository.get.return_value = mock_records

        # Mock live trades
        trades = [
            Trade(
                id=str(i),
                symbol="BTC-USD",
                side=OrderSide.BUY,
                price=Decimal("42000") + Decimal(i * 100),
                quantity=Decimal("1.0"),
                timestamp=datetime(2024, 1, 1, 12, i, 0, tzinfo=UTC),
            )
            for i in range(10)
        ]
        mock_exchange.get_recent_trades.return_value = trades

        feed = HybridDataFeed(mock_exchange, mock_repository, store_data=False)
        result = await feed.get_ohlcv("BTC-USD", "1m", limit=10)

        # Should have merged data
        assert len(result) >= 3  # At least the historical data
