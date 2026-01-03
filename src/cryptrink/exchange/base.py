"""Abstract base class for exchange implementations."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class OrderSide(str, Enum):
    """Order side (buy or sell)."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type."""

    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    """Order status."""

    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True)
class Ticker:
    """Market ticker data."""

    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume_24h: Decimal
    high_24h: Decimal
    low_24h: Decimal
    timestamp: datetime


@dataclass(frozen=True)
class OrderBookLevel:
    """Single level in the order book."""

    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class OrderBook:
    """Order book snapshot."""

    symbol: str
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    timestamp: datetime

    @property
    def best_bid(self) -> Decimal | None:
        """Get best bid price."""
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        """Get best ask price."""
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Decimal | None:
        """Get bid-ask spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None


@dataclass(frozen=True)
class Trade:
    """Executed trade."""

    id: str
    symbol: str
    side: OrderSide
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    fee: Decimal = Decimal("0")
    fee_currency: str = ""


@dataclass(frozen=True)
class Order:
    """Order representation."""

    id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    quantity: Decimal
    filled_quantity: Decimal
    price: Decimal | None  # None for market orders
    stop_price: Decimal | None
    created_at: datetime
    updated_at: datetime
    trades: tuple[Trade, ...] = field(default_factory=tuple)

    @property
    def remaining_quantity(self) -> Decimal:
        """Get remaining unfilled quantity."""
        return self.quantity - self.filled_quantity

    @property
    def is_active(self) -> bool:
        """Check if order is still active."""
        return self.status in (
            OrderStatus.PENDING,
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
        )

    @property
    def average_fill_price(self) -> Decimal | None:
        """Calculate average fill price from trades."""
        if not self.trades:
            return None
        total_value = sum((t.price * t.quantity for t in self.trades), Decimal("0"))
        total_quantity = sum((t.quantity for t in self.trades), Decimal("0"))
        if total_quantity == 0:
            return None
        return Decimal(total_value / total_quantity)


@dataclass(frozen=True)
class Balance:
    """Account balance for a currency."""

    currency: str
    available: Decimal
    locked: Decimal

    @property
    def total(self) -> Decimal:
        """Get total balance (available + locked)."""
        return self.available + self.locked


class ExchangeError(Exception):
    """Base exception for exchange errors."""

    pass


class AuthenticationError(ExchangeError):
    """Authentication failed."""

    pass


class RateLimitError(ExchangeError):
    """Rate limit exceeded."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class InsufficientFundsError(ExchangeError):
    """Insufficient funds for operation."""

    pass


class OrderNotFoundError(ExchangeError):
    """Order not found."""

    pass


class BaseExchange(ABC):
    """Abstract base class for exchange implementations.

    All exchange connectors must implement this interface to ensure
    consistent behavior across different exchanges.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Exchange name."""
        ...

    @property
    @abstractmethod
    def is_sandbox(self) -> bool:
        """Whether connected to sandbox/testnet environment."""
        ...

    # Market Data Methods

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """Get current ticker for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., "BTC-EUR").

        Returns:
            Current ticker data.

        Raises:
            ExchangeError: If request fails.
        """
        ...

    @abstractmethod
    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """Get order book for a symbol.

        Args:
            symbol: Trading pair symbol.
            depth: Number of levels to fetch.

        Returns:
            Order book snapshot.

        Raises:
            ExchangeError: If request fails.
        """
        ...

    @abstractmethod
    async def get_recent_trades(self, symbol: str, limit: int = 100) -> list[Trade]:
        """Get recent trades for a symbol.

        Args:
            symbol: Trading pair symbol.
            limit: Maximum number of trades to return.

        Returns:
            List of recent trades.

        Raises:
            ExchangeError: If request fails.
        """
        ...

    @abstractmethod
    async def get_symbols(self) -> list[str]:
        """Get list of available trading symbols.

        Returns:
            List of trading pair symbols.

        Raises:
            ExchangeError: If request fails.
        """
        ...

    # Account Methods

    @abstractmethod
    async def get_balances(self) -> dict[str, Balance]:
        """Get all account balances.

        Returns:
            Dictionary mapping currency to balance.

        Raises:
            AuthenticationError: If not authenticated.
            ExchangeError: If request fails.
        """
        ...

    @abstractmethod
    async def get_balance(self, currency: str) -> Balance:
        """Get balance for a specific currency.

        Args:
            currency: Currency code (e.g., "EUR", "BTC").

        Returns:
            Balance for the currency.

        Raises:
            AuthenticationError: If not authenticated.
            ExchangeError: If request fails.
        """
        ...

    # Order Methods

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
        stop_price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        """Create a new order.

        Args:
            symbol: Trading pair symbol.
            side: Buy or sell.
            order_type: Type of order.
            quantity: Order quantity.
            price: Limit price (required for limit orders).
            stop_price: Stop price (for stop orders).
            client_order_id: Optional client-specified order ID.

        Returns:
            Created order.

        Raises:
            InsufficientFundsError: If balance is insufficient.
            ExchangeError: If order creation fails.
        """
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str | None = None) -> Order:
        """Cancel an open order.

        Args:
            order_id: Order ID to cancel.
            symbol: Optional symbol (required by some exchanges).

        Returns:
            Cancelled order.

        Raises:
            OrderNotFoundError: If order not found.
            ExchangeError: If cancellation fails.
        """
        ...

    @abstractmethod
    async def get_order(self, order_id: str, symbol: str | None = None) -> Order:
        """Get order by ID.

        Args:
            order_id: Order ID.
            symbol: Optional symbol (required by some exchanges).

        Returns:
            Order details.

        Raises:
            OrderNotFoundError: If order not found.
            ExchangeError: If request fails.
        """
        ...

    @abstractmethod
    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        """Get all open orders.

        Args:
            symbol: Optional symbol to filter by.

        Returns:
            List of open orders.

        Raises:
            ExchangeError: If request fails.
        """
        ...

    @abstractmethod
    async def get_order_history(
        self,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[Order]:
        """Get order history.

        Args:
            symbol: Optional symbol to filter by.
            limit: Maximum number of orders to return.

        Returns:
            List of historical orders.

        Raises:
            ExchangeError: If request fails.
        """
        ...

    # Streaming Methods (optional - not all exchanges support)

    async def stream_ticker(self, symbol: str) -> AsyncIterator[Ticker]:
        """Stream real-time ticker updates.

        Args:
            symbol: Trading pair symbol.

        Yields:
            Ticker updates.

        Raises:
            NotImplementedError: If streaming not supported.
        """
        raise NotImplementedError("Ticker streaming not supported")
        yield  # Make this a generator

    async def stream_orderbook(self, symbol: str) -> AsyncIterator[OrderBook]:
        """Stream real-time order book updates.

        Args:
            symbol: Trading pair symbol.

        Yields:
            Order book updates.

        Raises:
            NotImplementedError: If streaming not supported.
        """
        raise NotImplementedError("Order book streaming not supported")
        yield  # Make this a generator

    async def stream_trades(self, symbol: str) -> AsyncIterator[Trade]:
        """Stream real-time trade updates.

        Args:
            symbol: Trading pair symbol.

        Yields:
            Trade updates.

        Raises:
            NotImplementedError: If streaming not supported.
        """
        raise NotImplementedError("Trade streaming not supported")
        yield  # Make this a generator

    # Lifecycle Methods

    async def connect(self) -> None:
        """Establish connection to exchange.

        Override if exchange requires explicit connection.
        """
        pass

    async def close(self) -> None:
        """Close connection to exchange.

        Override if exchange requires cleanup.
        """
        pass

    async def __aenter__(self) -> "BaseExchange":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Async context manager exit."""
        await self.close()
