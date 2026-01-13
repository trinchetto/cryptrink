"""Database models and repository for OHLCV data storage.

This module provides SQLAlchemy models and a repository pattern for storing
and retrieving OHLCV (Open, High, Low, Close, Volume) candlestick data.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, String, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from cryptrink.core.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class OHLCV(Base):
    """OHLCV candlestick data model.

    Stores Open, High, Low, Close, Volume data for a symbol at a specific timeframe.
    """

    __tablename__ = "ohlcv"

    # Primary key: symbol + timeframe + timestamp
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Symbol (e.g., "BTC-USD")
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Timeframe (e.g., "1m", "5m", "1h", "1d")
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    # Timestamp (Unix timestamp in milliseconds)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # OHLCV data (stored as strings to preserve precision)
    open: Mapped[str] = mapped_column(String(50), nullable=False)
    high: Mapped[str] = mapped_column(String(50), nullable=False)
    low: Mapped[str] = mapped_column(String(50), nullable=False)
    close: Mapped[str] = mapped_column(String(50), nullable=False)
    volume: Mapped[str] = mapped_column(String(50), nullable=False)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)

    def __repr__(self) -> str:
        """String representation of OHLCV."""
        return (
            f"OHLCV(symbol={self.symbol!r}, timeframe={self.timeframe!r}, "
            f"timestamp={self.timestamp}, close={self.close})"
        )

    @property
    def open_decimal(self) -> Decimal:
        """Get open price as Decimal."""
        return Decimal(self.open)

    @property
    def high_decimal(self) -> Decimal:
        """Get high price as Decimal."""
        return Decimal(self.high)

    @property
    def low_decimal(self) -> Decimal:
        """Get low price as Decimal."""
        return Decimal(self.low)

    @property
    def close_decimal(self) -> Decimal:
        """Get close price as Decimal."""
        return Decimal(self.close)

    @property
    def volume_decimal(self) -> Decimal:
        """Get volume as Decimal."""
        return Decimal(self.volume)

    @property
    def datetime(self) -> datetime:
        """Get timestamp as datetime object."""
        return datetime.fromtimestamp(self.timestamp / 1000.0, tz=UTC)


async def init_db(engine: AsyncEngine) -> None:
    """Initialize the database by creating all tables.

    Args:
        engine: SQLAlchemy async engine.
    """
    logger.info("Initializing database schema")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema initialized")


class OHLCVRepository:
    """Repository for OHLCV data access.

    Provides methods for storing and retrieving OHLCV data from the database.
    """

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        """Initialize the repository.

        Args:
            session_maker: SQLAlchemy async session maker.
        """
        self._session_maker = session_maker

    async def save(
        self,
        symbol: str,
        timeframe: str,
        timestamp: int,
        open_price: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal,
    ) -> OHLCV:
        """Save a single OHLCV record.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD").
            timeframe: Timeframe (e.g., "1m", "5m", "1h", "1d").
            timestamp: Unix timestamp in milliseconds.
            open_price: Opening price.
            high: Highest price.
            low: Lowest price.
            close: Closing price.
            volume: Trading volume.

        Returns:
            The saved OHLCV record.
        """
        async with self._session_maker() as session:
            ohlcv = OHLCV(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=timestamp,
                open=str(open_price),
                high=str(high),
                low=str(low),
                close=str(close),
                volume=str(volume),
            )
            session.add(ohlcv)
            await session.commit()
            await session.refresh(ohlcv)
            return ohlcv

    async def save_batch(self, ohlcv_records: list[dict[str, Any]]) -> int:
        """Save multiple OHLCV records in a batch.

        Args:
            ohlcv_records: List of dictionaries with OHLCV data.
                Each dict should have: symbol, timeframe, timestamp, open, high, low, close, volume.

        Returns:
            Number of records saved.
        """
        if not ohlcv_records:
            return 0

        async with self._session_maker() as session:
            records = [
                OHLCV(
                    symbol=record["symbol"],
                    timeframe=record["timeframe"],
                    timestamp=record["timestamp"],
                    open=str(record["open"]),
                    high=str(record["high"]),
                    low=str(record["low"]),
                    close=str(record["close"]),
                    volume=str(record["volume"]),
                )
                for record in ohlcv_records
            ]
            session.add_all(records)
            await session.commit()
            return len(records)

    async def get(
        self,
        symbol: str,
        timeframe: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
    ) -> list[OHLCV]:
        """Get OHLCV records for a symbol and timeframe.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD").
            timeframe: Timeframe (e.g., "1m", "5m", "1h", "1d").
            start_time: Optional start timestamp in milliseconds (inclusive).
            end_time: Optional end timestamp in milliseconds (inclusive).
            limit: Optional maximum number of records to return.

        Returns:
            List of OHLCV records, ordered by timestamp ascending.
        """
        async with self._session_maker() as session:
            query = select(OHLCV).where(OHLCV.symbol == symbol, OHLCV.timeframe == timeframe)

            if start_time is not None:
                query = query.where(OHLCV.timestamp >= start_time)

            if end_time is not None:
                query = query.where(OHLCV.timestamp <= end_time)

            query = query.order_by(OHLCV.timestamp.asc())

            if limit is not None:
                query = query.limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_latest(self, symbol: str, timeframe: str, count: int = 100) -> list[OHLCV]:
        """Get the latest N OHLCV records for a symbol and timeframe.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD").
            timeframe: Timeframe (e.g., "1m", "5m", "1h", "1d").
            count: Number of latest records to return (default: 100).

        Returns:
            List of OHLCV records, ordered by timestamp ascending.
        """
        async with self._session_maker() as session:
            query = (
                select(OHLCV)
                .where(OHLCV.symbol == symbol, OHLCV.timeframe == timeframe)
                .order_by(OHLCV.timestamp.desc())
                .limit(count)
            )

            result = await session.execute(query)
            records = list(result.scalars().all())
            # Reverse to get ascending order
            return list(reversed(records))

    async def delete_old(self, symbol: str, timeframe: str, before_timestamp: int) -> int:
        """Delete OHLCV records older than a specified timestamp.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD").
            timeframe: Timeframe (e.g., "1m", "5m", "1h", "1d").
            before_timestamp: Delete records with timestamp < this value.

        Returns:
            Number of records deleted.
        """
        async with self._session_maker() as session:
            query = select(OHLCV).where(
                OHLCV.symbol == symbol,
                OHLCV.timeframe == timeframe,
                OHLCV.timestamp < before_timestamp,
            )

            result = await session.execute(query)
            records = result.scalars().all()
            count = len(list(records))

            for record in records:
                await session.delete(record)

            await session.commit()
            return count


def create_engine(database_url: str, echo: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    Args:
        database_url: Database connection URL.
        echo: Whether to echo SQL statements (default: False).

    Returns:
        SQLAlchemy async engine.
    """
    return create_async_engine(database_url, echo=echo)


def create_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session maker.

    Args:
        engine: SQLAlchemy async engine.

    Returns:
        SQLAlchemy async session maker.
    """
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
