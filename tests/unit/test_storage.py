"""Unit tests for data storage module."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from cryptrink.data.storage import (
    OHLCV,
    OHLCVRepository,
    create_engine,
    create_session_maker,
    init_db,
)


@pytest.fixture
async def test_engine() -> AsyncEngine:
    """Create an in-memory SQLite engine for testing."""
    engine = create_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_db(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_maker(
    test_engine: AsyncEngine,
) -> async_sessionmaker:
    """Create a session maker for testing."""
    return create_session_maker(test_engine)


@pytest.fixture
def repository(session_maker: async_sessionmaker) -> OHLCVRepository:
    """Create an OHLCV repository for testing."""
    return OHLCVRepository(session_maker)


class TestOHLCVModel:
    """Tests for the OHLCV model."""

    def test_model_creation(self) -> None:
        """Test creating an OHLCV model instance."""
        ohlcv = OHLCV(
            symbol="BTC-USD",
            timeframe="1h",
            timestamp=1704067200000,  # 2024-01-01 00:00:00 UTC
            open="42000.50",
            high="42500.00",
            low="41800.00",
            close="42300.75",
            volume="150.25",
        )

        assert ohlcv.symbol == "BTC-USD"
        assert ohlcv.timeframe == "1h"
        assert ohlcv.timestamp == 1704067200000
        assert ohlcv.open == "42000.50"
        assert ohlcv.high == "42500.00"
        assert ohlcv.low == "41800.00"
        assert ohlcv.close == "42300.75"
        assert ohlcv.volume == "150.25"

    def test_decimal_properties(self) -> None:
        """Test Decimal property accessors."""
        ohlcv = OHLCV(
            symbol="BTC-USD",
            timeframe="1h",
            timestamp=1704067200000,
            open="42000.50",
            high="42500.00",
            low="41800.00",
            close="42300.75",
            volume="150.25",
        )

        assert ohlcv.open_decimal == Decimal("42000.50")
        assert ohlcv.high_decimal == Decimal("42500.00")
        assert ohlcv.low_decimal == Decimal("41800.00")
        assert ohlcv.close_decimal == Decimal("42300.75")
        assert ohlcv.volume_decimal == Decimal("150.25")

    def test_datetime_property(self) -> None:
        """Test datetime property accessor."""
        timestamp = 1704067200000  # 2024-01-01 00:00:00 UTC
        ohlcv = OHLCV(
            symbol="BTC-USD",
            timeframe="1h",
            timestamp=timestamp,
            open="42000.50",
            high="42500.00",
            low="41800.00",
            close="42300.75",
            volume="150.25",
        )

        dt = ohlcv.datetime
        assert dt == datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 1

    def test_repr(self) -> None:
        """Test string representation."""
        ohlcv = OHLCV(
            symbol="BTC-USD",
            timeframe="1h",
            timestamp=1704067200000,
            open="42000.50",
            high="42500.00",
            low="41800.00",
            close="42300.75",
            volume="150.25",
        )

        repr_str = repr(ohlcv)
        assert "BTC-USD" in repr_str
        assert "1h" in repr_str
        assert "1704067200000" in repr_str
        assert "42300.75" in repr_str


class TestOHLCVRepository:
    """Tests for the OHLCV repository."""

    async def test_save(self, repository: OHLCVRepository) -> None:
        """Test saving a single OHLCV record."""
        saved = await repository.save(
            symbol="BTC-USD",
            timeframe="1h",
            timestamp=1704067200000,
            open_price=Decimal("42000.50"),
            high=Decimal("42500.00"),
            low=Decimal("41800.00"),
            close=Decimal("42300.75"),
            volume=Decimal("150.25"),
        )

        assert saved.id is not None
        assert saved.symbol == "BTC-USD"
        assert saved.timeframe == "1h"
        assert saved.timestamp == 1704067200000
        assert saved.open_decimal == Decimal("42000.50")
        assert saved.high_decimal == Decimal("42500.00")
        assert saved.low_decimal == Decimal("41800.00")
        assert saved.close_decimal == Decimal("42300.75")
        assert saved.volume_decimal == Decimal("150.25")
        assert saved.created_at is not None

    async def test_save_batch(self, repository: OHLCVRepository) -> None:
        """Test saving multiple OHLCV records."""
        records = [
            {
                "symbol": "BTC-USD",
                "timeframe": "1h",
                "timestamp": 1704067200000,
                "open": Decimal("42000.00"),
                "high": Decimal("42500.00"),
                "low": Decimal("41800.00"),
                "close": Decimal("42300.00"),
                "volume": Decimal("100.00"),
            },
            {
                "symbol": "BTC-USD",
                "timeframe": "1h",
                "timestamp": 1704070800000,  # +1 hour
                "open": Decimal("42300.00"),
                "high": Decimal("42800.00"),
                "low": Decimal("42100.00"),
                "close": Decimal("42600.00"),
                "volume": Decimal("120.00"),
            },
            {
                "symbol": "BTC-USD",
                "timeframe": "1h",
                "timestamp": 1704074400000,  # +2 hours
                "open": Decimal("42600.00"),
                "high": Decimal("43000.00"),
                "low": Decimal("42400.00"),
                "close": Decimal("42900.00"),
                "volume": Decimal("90.00"),
            },
        ]

        count = await repository.save_batch(records)
        assert count == 3

        # Verify records were saved
        saved = await repository.get("BTC-USD", "1h")
        assert len(saved) == 3
        assert saved[0].timestamp == 1704067200000
        assert saved[1].timestamp == 1704070800000
        assert saved[2].timestamp == 1704074400000

    async def test_save_batch_empty(self, repository: OHLCVRepository) -> None:
        """Test saving an empty batch."""
        count = await repository.save_batch([])
        assert count == 0

    async def test_get_all(self, repository: OHLCVRepository) -> None:
        """Test getting all records for a symbol and timeframe."""
        # Save some records
        await repository.save_batch(
            [
                {
                    "symbol": "BTC-USD",
                    "timeframe": "1h",
                    "timestamp": 1704067200000 + i * 3600000,
                    "open": Decimal(f"{42000 + i * 100}"),
                    "high": Decimal(f"{42500 + i * 100}"),
                    "low": Decimal(f"{41800 + i * 100}"),
                    "close": Decimal(f"{42300 + i * 100}"),
                    "volume": Decimal(f"{100 + i * 10}"),
                }
                for i in range(5)
            ]
        )

        # Get all records
        records = await repository.get("BTC-USD", "1h")
        assert len(records) == 5
        # Verify ascending order
        for i, record in enumerate(records):
            assert record.timestamp == 1704067200000 + i * 3600000

    async def test_get_with_time_range(self, repository: OHLCVRepository) -> None:
        """Test getting records within a time range."""
        # Save 10 records
        await repository.save_batch(
            [
                {
                    "symbol": "BTC-USD",
                    "timeframe": "1h",
                    "timestamp": 1704067200000 + i * 3600000,
                    "open": Decimal(f"{42000 + i * 100}"),
                    "high": Decimal(f"{42500 + i * 100}"),
                    "low": Decimal(f"{41800 + i * 100}"),
                    "close": Decimal(f"{42300 + i * 100}"),
                    "volume": Decimal(f"{100 + i * 10}"),
                }
                for i in range(10)
            ]
        )

        # Get records from index 2 to 6 (inclusive)
        start_time = 1704067200000 + 2 * 3600000
        end_time = 1704067200000 + 6 * 3600000

        records = await repository.get("BTC-USD", "1h", start_time=start_time, end_time=end_time)

        assert len(records) == 5
        assert records[0].timestamp == start_time
        assert records[-1].timestamp == end_time

    async def test_get_with_limit(self, repository: OHLCVRepository) -> None:
        """Test getting records with a limit."""
        # Save 10 records
        await repository.save_batch(
            [
                {
                    "symbol": "BTC-USD",
                    "timeframe": "1h",
                    "timestamp": 1704067200000 + i * 3600000,
                    "open": Decimal(f"{42000 + i * 100}"),
                    "high": Decimal(f"{42500 + i * 100}"),
                    "low": Decimal(f"{41800 + i * 100}"),
                    "close": Decimal(f"{42300 + i * 100}"),
                    "volume": Decimal(f"{100 + i * 10}"),
                }
                for i in range(10)
            ]
        )

        # Get only first 3 records
        records = await repository.get("BTC-USD", "1h", limit=3)

        assert len(records) == 3
        assert records[0].timestamp == 1704067200000
        assert records[2].timestamp == 1704067200000 + 2 * 3600000

    async def test_get_latest(self, repository: OHLCVRepository) -> None:
        """Test getting the latest N records."""
        # Save 10 records
        await repository.save_batch(
            [
                {
                    "symbol": "BTC-USD",
                    "timeframe": "1h",
                    "timestamp": 1704067200000 + i * 3600000,
                    "open": Decimal(f"{42000 + i * 100}"),
                    "high": Decimal(f"{42500 + i * 100}"),
                    "low": Decimal(f"{41800 + i * 100}"),
                    "close": Decimal(f"{42300 + i * 100}"),
                    "volume": Decimal(f"{100 + i * 10}"),
                }
                for i in range(10)
            ]
        )

        # Get latest 3 records
        records = await repository.get_latest("BTC-USD", "1h", count=3)

        assert len(records) == 3
        # Should be in ascending order
        assert records[0].timestamp == 1704067200000 + 7 * 3600000
        assert records[1].timestamp == 1704067200000 + 8 * 3600000
        assert records[2].timestamp == 1704067200000 + 9 * 3600000

    async def test_get_different_symbols(self, repository: OHLCVRepository) -> None:
        """Test that different symbols are isolated."""
        # Save records for two different symbols
        await repository.save(
            "BTC-USD",
            "1h",
            1704067200000,
            Decimal("42000"),
            Decimal("42500"),
            Decimal("41800"),
            Decimal("42300"),
            Decimal("100"),
        )
        await repository.save(
            "ETH-USD",
            "1h",
            1704067200000,
            Decimal("2200"),
            Decimal("2250"),
            Decimal("2180"),
            Decimal("2230"),
            Decimal("500"),
        )

        btc_records = await repository.get("BTC-USD", "1h")
        eth_records = await repository.get("ETH-USD", "1h")

        assert len(btc_records) == 1
        assert len(eth_records) == 1
        assert btc_records[0].symbol == "BTC-USD"
        assert eth_records[0].symbol == "ETH-USD"

    async def test_get_different_timeframes(self, repository: OHLCVRepository) -> None:
        """Test that different timeframes are isolated."""
        # Save records for same symbol but different timeframes
        await repository.save(
            "BTC-USD",
            "1h",
            1704067200000,
            Decimal("42000"),
            Decimal("42500"),
            Decimal("41800"),
            Decimal("42300"),
            Decimal("100"),
        )
        await repository.save(
            "BTC-USD",
            "1d",
            1704067200000,
            Decimal("42000"),
            Decimal("43000"),
            Decimal("41000"),
            Decimal("42500"),
            Decimal("2000"),
        )

        hourly = await repository.get("BTC-USD", "1h")
        daily = await repository.get("BTC-USD", "1d")

        assert len(hourly) == 1
        assert len(daily) == 1
        assert hourly[0].timeframe == "1h"
        assert daily[0].timeframe == "1d"

    async def test_delete_old(self, repository: OHLCVRepository) -> None:
        """Test deleting old records."""
        # Save 10 records
        await repository.save_batch(
            [
                {
                    "symbol": "BTC-USD",
                    "timeframe": "1h",
                    "timestamp": 1704067200000 + i * 3600000,
                    "open": Decimal(f"{42000 + i * 100}"),
                    "high": Decimal(f"{42500 + i * 100}"),
                    "low": Decimal(f"{41800 + i * 100}"),
                    "close": Decimal(f"{42300 + i * 100}"),
                    "volume": Decimal(f"{100 + i * 10}"),
                }
                for i in range(10)
            ]
        )

        # Delete records before index 5
        before_timestamp = 1704067200000 + 5 * 3600000
        deleted_count = await repository.delete_old("BTC-USD", "1h", before_timestamp)

        assert deleted_count == 5

        # Verify remaining records
        remaining = await repository.get("BTC-USD", "1h")
        assert len(remaining) == 5
        assert all(r.timestamp >= before_timestamp for r in remaining)


class TestDatabaseInitialization:
    """Tests for database initialization."""

    async def test_init_db(self) -> None:
        """Test database initialization."""
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)

        # Verify we can create a session and query
        session_maker = create_session_maker(engine)
        repository = OHLCVRepository(session_maker)

        # Should be able to save without errors
        await repository.save(
            "BTC-USD",
            "1h",
            1704067200000,
            Decimal("42000"),
            Decimal("42500"),
            Decimal("41800"),
            Decimal("42300"),
            Decimal("100"),
        )

        await engine.dispose()
