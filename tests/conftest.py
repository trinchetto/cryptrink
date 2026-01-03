"""Pytest configuration and fixtures."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from cryptrink.core.config import Settings
from cryptrink.exchange.base import Balance, OrderBook, OrderBookLevel, Ticker


@pytest.fixture
def mock_settings() -> Settings:
    """Create test settings."""
    return Settings(
        execution_mode="paper",
        symbols=["BTC-EUR", "ETH-EUR"],
        log_level="DEBUG",
    )


@pytest.fixture
def sample_ticker() -> Ticker:
    """Create a sample ticker for testing."""
    return Ticker(
        symbol="BTC-EUR",
        bid=Decimal("42000.00"),
        ask=Decimal("42010.00"),
        last=Decimal("42005.00"),
        volume_24h=Decimal("1234.56"),
        high_24h=Decimal("43000.00"),
        low_24h=Decimal("41000.00"),
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def sample_orderbook() -> OrderBook:
    """Create a sample order book for testing."""
    return OrderBook(
        symbol="BTC-EUR",
        bids=(
            OrderBookLevel(price=Decimal("42000.00"), quantity=Decimal("1.5")),
            OrderBookLevel(price=Decimal("41990.00"), quantity=Decimal("2.0")),
            OrderBookLevel(price=Decimal("41980.00"), quantity=Decimal("3.5")),
        ),
        asks=(
            OrderBookLevel(price=Decimal("42010.00"), quantity=Decimal("1.0")),
            OrderBookLevel(price=Decimal("42020.00"), quantity=Decimal("2.5")),
            OrderBookLevel(price=Decimal("42030.00"), quantity=Decimal("1.8")),
        ),
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def sample_balances() -> dict[str, Balance]:
    """Create sample account balances."""
    return {
        "EUR": Balance(currency="EUR", available=Decimal("10000.00"), locked=Decimal("0")),
        "BTC": Balance(currency="BTC", available=Decimal("0.5"), locked=Decimal("0.1")),
        "ETH": Balance(currency="ETH", available=Decimal("5.0"), locked=Decimal("0")),
    }


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """Create sample OHLCV data for testing."""
    data: dict[str, list[Any]] = {
        "timestamp": pd.date_range(start="2024-01-01", periods=100, freq="1h"),
        "open": [Decimal("40000") + Decimal(i * 10) for i in range(100)],
        "high": [Decimal("40050") + Decimal(i * 10) for i in range(100)],
        "low": [Decimal("39950") + Decimal(i * 10) for i in range(100)],
        "close": [Decimal("40025") + Decimal(i * 10) for i in range(100)],
        "volume": [Decimal("100") + Decimal(i) for i in range(100)],
    }
    df = pd.DataFrame(data)
    df.set_index("timestamp", inplace=True)
    return df


@pytest.fixture
def mock_exchange() -> AsyncMock:
    """Create a mock exchange for testing."""
    exchange = AsyncMock()
    exchange.name = "mock_exchange"
    exchange.is_sandbox = True
    return exchange
