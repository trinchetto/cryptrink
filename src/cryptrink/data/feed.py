"""Data feed abstraction for live and historical market data.

This module provides a unified interface for accessing market data,
whether from a live exchange or historical storage.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import pandas as pd

from cryptrink.core.logging import get_logger
from cryptrink.data.historical import HistoricalDataFetcher, OHLCVAggregator
from cryptrink.data.indicators import ohlcv_to_dataframe
from cryptrink.data.storage import OHLCVRepository
from cryptrink.exchange.base import BaseExchange

logger = get_logger(__name__)


class BaseDataFeed(ABC):
    """Abstract base class for data feeds.

    Provides a unified interface for accessing OHLCV data and calculating
    indicators, regardless of whether the data comes from live exchange
    or historical storage.
    """

    @abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Get OHLCV data.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD").
            timeframe: Timeframe (e.g., "1m", "5m", "1h", "1d").
            limit: Maximum number of candles to return.
            start_time: Optional start time filter.
            end_time: Optional end time filter.

        Returns:
            List of OHLCV dictionaries.
        """
        pass

    async def get_ohlcv_dataframe(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> pd.DataFrame:
        """Get OHLCV data as a pandas DataFrame.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD").
            timeframe: Timeframe (e.g., "1m", "5m", "1h", "1d").
            limit: Maximum number of candles to return.
            start_time: Optional start time filter.
            end_time: Optional end time filter.

        Returns:
            DataFrame with datetime index and OHLCV columns.
        """
        ohlcv_data = await self.get_ohlcv(symbol, timeframe, limit, start_time, end_time)
        return ohlcv_to_dataframe(ohlcv_data)


class LiveDataFeed(BaseDataFeed):
    """Live data feed that fetches real-time data from an exchange.

    Aggregates recent trades into OHLCV candles on-the-fly.
    Optionally stores data in the repository for future use.
    """

    def __init__(
        self,
        exchange: BaseExchange,
        repository: OHLCVRepository | None = None,
        store_data: bool = True,
    ) -> None:
        """Initialize the live data feed.

        Args:
            exchange: Exchange client instance.
            repository: Optional OHLCV repository for storing data.
            store_data: Whether to store fetched data (default: True).
        """
        self._exchange = exchange
        self._repository = repository
        self._store_data = store_data
        self._fetcher = HistoricalDataFetcher(exchange)
        self._aggregator = OHLCVAggregator()

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Get OHLCV data from live exchange."""
        logger.info("Fetching live OHLCV data", symbol=symbol, timeframe=timeframe, limit=limit)

        # Fetch and aggregate recent trades
        ohlcv_data = await self._fetcher.fetch_ohlcv(symbol, timeframe, limit=limit * 10)

        # Apply time filters if specified
        if start_time or end_time:
            start_ms = int(start_time.timestamp() * 1000) if start_time else 0
            end_ms = int(end_time.timestamp() * 1000) if end_time else float("inf")
            ohlcv_data = [
                candle for candle in ohlcv_data if start_ms <= candle["timestamp"] <= end_ms
            ]

        # Apply limit
        if len(ohlcv_data) > limit:
            ohlcv_data = ohlcv_data[-limit:]

        # Store data if enabled and repository available
        if self._store_data and self._repository and ohlcv_data:
            try:
                await self._repository.save_batch(ohlcv_data)
                logger.debug("Stored OHLCV data", symbol=symbol, candles=len(ohlcv_data))
            except Exception as e:
                logger.warning("Failed to store OHLCV data", error=str(e))

        return ohlcv_data


class HistoricalDataFeed(BaseDataFeed):
    """Historical data feed that reads from database storage.

    Retrieves previously stored OHLCV data from the repository.
    """

    def __init__(self, repository: OHLCVRepository) -> None:
        """Initialize the historical data feed.

        Args:
            repository: OHLCV repository for reading data.
        """
        self._repository = repository

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Get OHLCV data from database storage."""
        logger.info(
            "Fetching historical OHLCV data",
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )

        # Convert datetime to milliseconds
        start_ms = int(start_time.timestamp() * 1000) if start_time else None
        end_ms = int(end_time.timestamp() * 1000) if end_time else None

        # Fetch from repository
        records = await self._repository.get(
            symbol, timeframe, start_time=start_ms, end_time=end_ms, limit=limit
        )

        # Convert OHLCV models to dictionaries
        ohlcv_data = [
            {
                "symbol": record.symbol,
                "timeframe": record.timeframe,
                "timestamp": record.timestamp,
                "open": record.open_decimal,
                "high": record.high_decimal,
                "low": record.low_decimal,
                "close": record.close_decimal,
                "volume": record.volume_decimal,
            }
            for record in records
        ]

        logger.info(
            "Retrieved historical OHLCV data",
            symbol=symbol,
            timeframe=timeframe,
            candles=len(ohlcv_data),
        )

        return ohlcv_data


class HybridDataFeed(BaseDataFeed):
    """Hybrid data feed that uses both historical and live data.

    Attempts to fetch from historical storage first, then falls back
    to live exchange if data is not available or insufficient.
    """

    def __init__(
        self,
        exchange: BaseExchange,
        repository: OHLCVRepository,
        store_data: bool = True,
    ) -> None:
        """Initialize the hybrid data feed.

        Args:
            exchange: Exchange client instance.
            repository: OHLCV repository for reading/writing data.
            store_data: Whether to store live data (default: True).
        """
        self._historical_feed = HistoricalDataFeed(repository)
        self._live_feed = LiveDataFeed(exchange, repository, store_data)

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Get OHLCV data using hybrid approach."""
        logger.info(
            "Fetching OHLCV data (hybrid mode)",
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )

        # Try historical data first
        historical_data = await self._historical_feed.get_ohlcv(
            symbol, timeframe, limit, start_time, end_time
        )

        # Check if we have enough data
        if len(historical_data) >= limit:
            logger.debug(
                "Using historical data",
                symbol=symbol,
                candles=len(historical_data),
            )
            return historical_data

        # Need more data from live feed
        logger.debug(
            "Insufficient historical data, fetching live data",
            symbol=symbol,
            historical_candles=len(historical_data),
            needed=limit,
        )

        live_data = await self._live_feed.get_ohlcv(symbol, timeframe, limit, start_time, end_time)

        # Merge historical and live data, removing duplicates
        if historical_data and live_data:
            # Get timestamps of historical data
            historical_timestamps = {candle["timestamp"] for candle in historical_data}

            # Add live data that doesn't exist in historical
            for candle in live_data:
                if candle["timestamp"] not in historical_timestamps:
                    historical_data.append(candle)

            # Sort by timestamp
            historical_data.sort(key=lambda x: x["timestamp"])

            # Apply limit
            if len(historical_data) > limit:
                historical_data = historical_data[-limit:]

            return historical_data

        # Return whichever we have
        return live_data if live_data else historical_data
