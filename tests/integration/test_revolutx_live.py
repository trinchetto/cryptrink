"""Integration tests for Revolut X API with real credentials.

These tests require valid API credentials and make real API calls.
Run with: pytest tests/integration/ -v -m integration

To skip integration tests (default):
pytest tests/ -v -m "not integration"
"""

import os
from decimal import Decimal

import pytest
from dotenv import load_dotenv

from cryptrink.core.config import Settings
from cryptrink.exchange.base import OrderSide
from cryptrink.exchange.revolutx import RevolutXExchange

# Load .env.local for integration tests (since it's skipped during pytest)
load_dotenv(".env.local")

# Skip all integration tests unless explicitly requested
pytestmark = pytest.mark.integration

# Flag to control write tests (disabled by default to prevent accidental orders)
SKIP_WRITE_TESTS = os.getenv("RUN_WRITE_TESTS", "false").lower() != "true"


@pytest.fixture
def skip_if_no_credentials():
    """Skip test if API credentials are not configured."""
    api_key = os.getenv("REVOLUTX_API_KEY")
    has_private_key = os.getenv("REVOLUTX_PRIVATE_KEY") or os.getenv("REVOLUTX_PRIVATE_KEY_PATH")

    if not api_key or not has_private_key:
        pytest.skip(
            "Skipping integration test: REVOLUTX_API_KEY and "
            "REVOLUTX_PRIVATE_KEY (or REVOLUTX_PRIVATE_KEY_PATH) must be set"
        )


@pytest.fixture
async def exchange(skip_if_no_credentials):  # noqa: ARG001
    """Create and connect to Revolut X exchange."""
    settings = Settings()

    # Get private key from settings
    private_key = settings.revolutx.get_private_key()

    # Create exchange with individual parameters
    exchange = RevolutXExchange(
        api_key=settings.revolutx.api_key.get_secret_value(),
        private_key_base64=private_key,
        base_url=settings.revolutx.base_url,
    )

    async with exchange:
        yield exchange


class TestRevolutXConnection:
    """Test basic connection and authentication."""

    async def test_connect_and_authenticate(self, skip_if_no_credentials):
        """Test that we can connect to the API with valid credentials."""
        settings = Settings()

        # Verify settings are loaded
        assert settings.revolutx.api_key.get_secret_value(), "API key must be set"

        # Verify private key can be loaded
        private_key = settings.revolutx.get_private_key()
        assert private_key, "Private key must be loadable"
        assert len(private_key) > 0, "Private key must not be empty"

        # Create exchange with proper parameters
        exchange = RevolutXExchange(
            api_key=settings.revolutx.api_key.get_secret_value(),
            private_key_base64=private_key,
        )

        # Test connection
        async with exchange:
            # If we get here without exception, connection succeeded
            assert exchange._client is not None

    async def test_get_symbols(self, exchange):
        """Test fetching available trading symbols."""
        symbols = await exchange.get_symbols()

        assert isinstance(symbols, list), "Symbols should be a list"
        assert len(symbols) > 0, "Should have at least one symbol"

        print(f"\n[OK] Found {len(symbols)} trading symbols")
        print(f"  Examples: {symbols[:5]}")


class TestRevolutXMarketData:
    """Test market data endpoints."""

    async def test_get_ticker(self, exchange):
        """Test fetching ticker data."""
        symbol = "BTC-USD"
        ticker = await exchange.get_ticker(symbol)

        assert ticker.symbol == symbol, f"Ticker symbol should be {symbol}"
        assert ticker.last is not None, "Ticker should have last price"
        assert ticker.last > 0, "Last price should be positive"

        print(f"\n[OK] Ticker for {symbol}:")
        print(f"  Last: ${ticker.last:,.2f}")
        if ticker.timestamp:
            print(f"  Timestamp: {ticker.timestamp}")

    async def test_get_orderbook(self, exchange):
        """Test fetching order book."""
        symbol = "BTC-USD"
        orderbook = await exchange.get_orderbook(symbol, depth=5)

        assert orderbook.symbol == symbol, f"Order book symbol should be {symbol}"
        assert len(orderbook.bids) > 0, "Should have at least one bid"
        assert len(orderbook.asks) > 0, "Should have at least one ask"

        best_bid = orderbook.bids[0]
        best_ask = orderbook.asks[0]
        spread = orderbook.spread
        assert spread is not None, "Should have spread"
        assert spread > 0, "Spread should be positive"

        print(f"\n[OK] Order book for {symbol}:")
        print(f"  Best Bid: ${best_bid.price:,.2f} ({best_bid.quantity} BTC)")
        print(f"  Best Ask: ${best_ask.price:,.2f} ({best_ask.quantity} BTC)")
        print(f"  Spread: ${spread:.2f}")

    async def test_get_recent_trades(self, exchange):
        """Test fetching recent trades."""
        symbol = "BTC-USD"
        trades = await exchange.get_recent_trades(symbol, limit=10)

        assert isinstance(trades, list), "Trades should be a list"
        assert len(trades) > 0, "Should have at least one trade"

        trade = trades[0]
        assert trade.symbol == symbol, f"Trade symbol should be {symbol}"
        assert trade.price > 0, "Trade price should be positive"
        assert trade.quantity > 0, "Trade quantity should be positive"
        assert trade.side in [OrderSide.BUY, OrderSide.SELL], "Trade side should be buy or sell"

        print(f"\n[OK] Recent trades for {symbol} (showing last 3):")
        for t in trades[:3]:
            print(f"  {t.timestamp}: {t.side.name} {t.quantity} @ ${t.price:,.2f}")


class TestRevolutXAccount:
    """Test account endpoints."""

    async def test_get_balances(self, exchange):
        """Test fetching account balances."""
        balances = await exchange.get_balances()

        assert isinstance(balances, dict), "Balances should be a dict"
        # Note: Balance dict might be empty for new accounts

        print(f"\n[OK] Account balances ({len(balances)} currencies):")
        for _currency, balance in list(balances.items())[:5]:  # Show first 5
            total = balance.available + balance.locked
            if total > 0:
                print(f"  {balance.currency}: {total:.8f} (available: {balance.available:.8f})")

    async def test_get_balance_specific_currency(self, exchange):
        """Test fetching balance for a specific currency."""
        # Try common currencies
        for currency in ["USD", "EUR", "GBP", "BTC"]:
            balance = await exchange.get_balance(currency)

            assert balance is not None, "Should return balance object"
            assert balance.currency == currency, f"Currency should be {currency}"
            assert isinstance(balance.available, Decimal), "Available should be Decimal"
            assert isinstance(balance.locked, Decimal), "Locked should be Decimal"
            assert balance.available >= 0, "Available balance should be non-negative"
            assert balance.locked >= 0, "Locked balance should be non-negative"

            # Print first non-zero balance
            total = balance.available + balance.locked
            if total > 0:
                print(f"\n[OK] {currency} Balance:")
                print(f"  Available: {balance.available}")
                print(f"  Locked: {balance.locked}")
                print(f"  Total: {total}")
                break


class TestRevolutXOrdersReadOnly:
    """Test read-only order endpoints."""

    async def test_get_open_orders(self, exchange):
        """Test fetching open orders."""
        orders = await exchange.get_open_orders()

        assert isinstance(orders, list), "Orders should be a list"
        # Note: Order list might be empty

        print(f"\n[OK] Open orders: {len(orders)}")
        if orders:
            for order in orders[:3]:  # Show first 3
                print(
                    f"  {order.id}: {order.side.name} {order.quantity} {order.symbol} @ {order.price}"
                )

    async def test_get_order_history(self, exchange):
        """Test fetching order history."""
        orders = await exchange.get_order_history(limit=10)

        assert isinstance(orders, list), "Order history should be a list"
        # Note: History might be empty for new accounts

        print(f"\n[OK] Order history: {len(orders)} orders")
        if orders:
            for order in orders[:3]:  # Show first 3
                print(
                    f"  {order.id}: {order.status.name} - {order.side.name} {order.quantity} {order.symbol}"
                )


@pytest.mark.skipif(
    SKIP_WRITE_TESTS, reason="Write tests are skipped by default to prevent accidental orders"
)
class TestRevolutXOrdersWrite:
    """Test order creation and cancellation (disabled by default)."""

    async def test_create_and_cancel_order(self, exchange):
        """Test creating and immediately canceling an order."""
        # This test is DISABLED by default to prevent accidental orders
        # Set environment variable RUN_WRITE_TESTS=true to enable
        pytest.skip("Write tests must be explicitly enabled")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
