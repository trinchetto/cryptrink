"""Exchange module for Cryptrink trading agent."""

from cryptrink.exchange.auth import RevolutXAuth, SignedRequest
from cryptrink.exchange.base import (
    AuthenticationError,
    Balance,
    BaseExchange,
    ExchangeError,
    InsufficientFundsError,
    Order,
    OrderBook,
    OrderNotFoundError,
    OrderSide,
    OrderStatus,
    OrderType,
    RateLimitError,
    Ticker,
    Trade,
)
from cryptrink.exchange.rate_limiter import (
    EndpointRateLimiter,
    RateLimitConfig,
    RateLimiter,
    with_retry,
)
from cryptrink.exchange.revolutx import RevolutXExchange

__all__ = [
    # Auth
    "RevolutXAuth",
    "SignedRequest",
    # Base classes and types
    "AuthenticationError",
    "Balance",
    "BaseExchange",
    "ExchangeError",
    "InsufficientFundsError",
    "Order",
    "OrderBook",
    "OrderNotFoundError",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "RateLimitError",
    "Ticker",
    "Trade",
    # Rate limiting
    "EndpointRateLimiter",
    "RateLimitConfig",
    "RateLimiter",
    "with_retry",
    # Revolut X
    "RevolutXExchange",
]
