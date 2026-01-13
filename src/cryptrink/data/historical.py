"""Historical data fetcher and OHLCV aggregation.

This module provides functionality to fetch historical trade data and aggregate
it into OHLCV (Open, High, Low, Close, Volume) candlesticks for various timeframes.
"""

from datetime import UTC, datetime
from typing import Any

from cryptrink.core.logging import get_logger
from cryptrink.exchange.base import BaseExchange, Trade

logger = get_logger(__name__)

# Timeframe definitions in seconds
TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


class OHLCVAggregator:
    """Aggregates trade data into OHLCV candlesticks."""

    @staticmethod
    def aggregate_trades(
        trades: list[Trade],
        timeframe: str,
    ) -> list[dict[str, Any]]:
        """Aggregate trades into OHLCV candlesticks.

        Args:
            trades: List of trades to aggregate, should be sorted by timestamp.
            timeframe: Timeframe for candles (e.g., "1m", "5m", "1h", "1d").

        Returns:
            List of OHLCV dictionaries with keys:
            - symbol: Trading pair symbol
            - timeframe: Timeframe string
            - timestamp: Candle start timestamp in milliseconds
            - open: Opening price as Decimal
            - high: Highest price as Decimal
            - low: Lowest price as Decimal
            - close: Closing price as Decimal
            - volume: Total volume as Decimal

        Raises:
            ValueError: If timeframe is not supported.
        """
        if not trades:
            return []

        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(
                f"Unsupported timeframe: {timeframe}. "
                f"Supported: {', '.join(TIMEFRAME_SECONDS.keys())}"
            )

        timeframe_seconds = TIMEFRAME_SECONDS[timeframe]
        symbol = trades[0].symbol

        # Group trades by candle timestamp
        candles: dict[int, list[Trade]] = {}

        for trade in trades:
            # Calculate candle start timestamp
            timestamp_seconds = int(trade.timestamp.timestamp())
            candle_start = (timestamp_seconds // timeframe_seconds) * timeframe_seconds
            candle_timestamp_ms = candle_start * 1000

            if candle_timestamp_ms not in candles:
                candles[candle_timestamp_ms] = []
            candles[candle_timestamp_ms].append(trade)

        # Build OHLCV data for each candle
        ohlcv_data = []
        for candle_timestamp_ms in sorted(candles.keys()):
            candle_trades = candles[candle_timestamp_ms]

            # Get prices and volumes
            prices = [trade.price for trade in candle_trades]
            volumes = [trade.quantity for trade in candle_trades]

            # First trade is open, last trade is close
            open_price = candle_trades[0].price
            close_price = candle_trades[-1].price
            high_price = max(prices)
            low_price = min(prices)
            volume = sum(volumes)

            ohlcv_data.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timestamp": candle_timestamp_ms,
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "close": close_price,
                    "volume": volume,
                }
            )

        return ohlcv_data


class HistoricalDataFetcher:
    """Fetches historical market data from an exchange."""

    def __init__(self, exchange: BaseExchange) -> None:
        """Initialize the historical data fetcher.

        Args:
            exchange: Exchange client instance.
        """
        self._exchange = exchange

    async def fetch_recent_trades(
        self,
        symbol: str,
        limit: int = 1000,
    ) -> list[Trade]:
        """Fetch recent trades for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD").
            limit: Maximum number of trades to fetch (default: 1000).

        Returns:
            List of trades, sorted by timestamp ascending.
        """
        logger.info("Fetching recent trades", symbol=symbol, limit=limit)
        trades = await self._exchange.get_recent_trades(symbol, limit=limit)

        # Ensure trades are sorted by timestamp ascending
        trades.sort(key=lambda t: t.timestamp)

        logger.info(
            "Fetched recent trades",
            symbol=symbol,
            count=len(trades),
            first_trade=trades[0].timestamp.isoformat() if trades else None,
            last_trade=trades[-1].timestamp.isoformat() if trades else None,
        )
        return trades

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch and aggregate OHLCV data from recent trades.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD").
            timeframe: Timeframe for candles (e.g., "1m", "5m", "1h", "1d").
            limit: Maximum number of trades to fetch for aggregation (default: 1000).

        Returns:
            List of OHLCV dictionaries, sorted by timestamp ascending.

        Raises:
            ValueError: If timeframe is not supported.
        """
        logger.info("Fetching OHLCV data", symbol=symbol, timeframe=timeframe, limit=limit)

        # Fetch recent trades
        trades = await self.fetch_recent_trades(symbol, limit=limit)

        if not trades:
            logger.warning("No trades found for symbol", symbol=symbol)
            return []

        # Aggregate into OHLCV
        aggregator = OHLCVAggregator()
        ohlcv_data = aggregator.aggregate_trades(trades, timeframe)

        logger.info(
            "Aggregated OHLCV data",
            symbol=symbol,
            timeframe=timeframe,
            candles=len(ohlcv_data),
            first_candle=datetime.fromtimestamp(
                ohlcv_data[0]["timestamp"] / 1000.0, tz=UTC
            ).isoformat()
            if ohlcv_data
            else None,
            last_candle=datetime.fromtimestamp(
                ohlcv_data[-1]["timestamp"] / 1000.0, tz=UTC
            ).isoformat()
            if ohlcv_data
            else None,
        )

        return ohlcv_data

    async def backfill_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Backfill OHLCV data for a time range.

        Note: This is a basic implementation that fetches recent trades.
        For true historical backfilling, the exchange would need to support
        fetching trades by time range, which Revolut X may not provide.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD").
            timeframe: Timeframe for candles (e.g., "1m", "5m", "1h", "1d").
            start_time: Start of time range (optional).
            end_time: End of time range (optional).

        Returns:
            List of OHLCV dictionaries within the time range.

        Raises:
            ValueError: If timeframe is not supported.
        """
        logger.info(
            "Backfilling OHLCV data",
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time.isoformat() if start_time else None,
            end_time=end_time.isoformat() if end_time else None,
        )

        # Fetch recent trades (this is limited by what the API provides)
        ohlcv_data = await self.fetch_ohlcv(symbol, timeframe, limit=1000)

        # Filter by time range if specified
        if start_time or end_time:
            start_ms = int(start_time.timestamp() * 1000) if start_time else 0
            end_ms = int(end_time.timestamp() * 1000) if end_time else float("inf")

            ohlcv_data = [
                candle for candle in ohlcv_data if start_ms <= candle["timestamp"] <= end_ms
            ]

            logger.info(
                "Filtered OHLCV data by time range",
                symbol=symbol,
                timeframe=timeframe,
                candles=len(ohlcv_data),
            )

        return ohlcv_data
