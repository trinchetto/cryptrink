"""Tests for exchange base classes."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cryptrink.exchange.base import (
    Balance,
    Order,
    OrderBook,
    OrderSide,
    OrderStatus,
    OrderType,
    RateLimitError,
    Ticker,
    Trade,
)


class TestTicker:
    """Tests for Ticker dataclass."""

    def test_ticker_creation(self, sample_ticker: Ticker) -> None:
        """Test ticker creation."""
        assert sample_ticker.symbol == "BTC-EUR"
        assert sample_ticker.bid == Decimal("42000.00")
        assert sample_ticker.ask == Decimal("42010.00")

    def test_ticker_is_frozen(self, sample_ticker: Ticker) -> None:
        """Test ticker is immutable."""
        with pytest.raises(AttributeError):
            sample_ticker.bid = Decimal("43000.00")  # type: ignore[misc]


class TestOrderBook:
    """Tests for OrderBook dataclass."""

    def test_orderbook_creation(self, sample_orderbook: OrderBook) -> None:
        """Test orderbook creation."""
        assert sample_orderbook.symbol == "BTC-EUR"
        assert len(sample_orderbook.bids) == 3
        assert len(sample_orderbook.asks) == 3

    def test_best_bid(self, sample_orderbook: OrderBook) -> None:
        """Test best bid retrieval."""
        assert sample_orderbook.best_bid == Decimal("42000.00")

    def test_best_ask(self, sample_orderbook: OrderBook) -> None:
        """Test best ask retrieval."""
        assert sample_orderbook.best_ask == Decimal("42010.00")

    def test_spread(self, sample_orderbook: OrderBook) -> None:
        """Test spread calculation."""
        assert sample_orderbook.spread == Decimal("10.00")

    def test_empty_orderbook(self) -> None:
        """Test empty orderbook properties."""
        empty_book = OrderBook(
            symbol="BTC-EUR",
            bids=(),
            asks=(),
            timestamp=datetime.now(UTC),
        )
        assert empty_book.best_bid is None
        assert empty_book.best_ask is None
        assert empty_book.spread is None


class TestBalance:
    """Tests for Balance dataclass."""

    def test_balance_total(self, sample_balances: dict[str, Balance]) -> None:
        """Test balance total calculation."""
        btc_balance = sample_balances["BTC"]
        assert btc_balance.total == Decimal("0.6")

    def test_available_balance(self, sample_balances: dict[str, Balance]) -> None:
        """Test available balance."""
        eur_balance = sample_balances["EUR"]
        assert eur_balance.available == Decimal("10000.00")
        assert eur_balance.locked == Decimal("0")


class TestOrder:
    """Tests for Order dataclass."""

    def test_order_remaining_quantity(self) -> None:
        """Test remaining quantity calculation."""
        order = Order(
            id="123",
            client_order_id="client-123",
            symbol="BTC-EUR",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            status=OrderStatus.PARTIALLY_FILLED,
            quantity=Decimal("1.0"),
            filled_quantity=Decimal("0.3"),
            price=Decimal("42000.00"),
            stop_price=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert order.remaining_quantity == Decimal("0.7")

    def test_order_is_active(self) -> None:
        """Test order active status."""
        active_order = Order(
            id="123",
            client_order_id="client-123",
            symbol="BTC-EUR",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            status=OrderStatus.OPEN,
            quantity=Decimal("1.0"),
            filled_quantity=Decimal("0"),
            price=Decimal("42000.00"),
            stop_price=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert active_order.is_active is True

        filled_order = Order(
            id="124",
            client_order_id="client-124",
            symbol="BTC-EUR",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            quantity=Decimal("1.0"),
            filled_quantity=Decimal("1.0"),
            price=None,
            stop_price=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert filled_order.is_active is False

    def test_average_fill_price(self) -> None:
        """Test average fill price calculation."""
        trades = (
            Trade(
                id="t1",
                symbol="BTC-EUR",
                side=OrderSide.BUY,
                price=Decimal("42000.00"),
                quantity=Decimal("0.5"),
                timestamp=datetime.now(UTC),
            ),
            Trade(
                id="t2",
                symbol="BTC-EUR",
                side=OrderSide.BUY,
                price=Decimal("42100.00"),
                quantity=Decimal("0.5"),
                timestamp=datetime.now(UTC),
            ),
        )
        order = Order(
            id="123",
            client_order_id="client-123",
            symbol="BTC-EUR",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            status=OrderStatus.FILLED,
            quantity=Decimal("1.0"),
            filled_quantity=Decimal("1.0"),
            price=Decimal("42000.00"),
            stop_price=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            trades=trades,
        )
        assert order.average_fill_price == Decimal("42050.00")


class TestRateLimitError:
    """Tests for RateLimitError exception."""

    def test_rate_limit_with_retry(self) -> None:
        """Test rate limit error with retry-after."""
        error = RateLimitError("Rate limit exceeded", retry_after=60.0)
        assert str(error) == "Rate limit exceeded"
        assert error.retry_after == 60.0

    def test_rate_limit_without_retry(self) -> None:
        """Test rate limit error without retry-after."""
        error = RateLimitError("Rate limit exceeded")
        assert error.retry_after is None
