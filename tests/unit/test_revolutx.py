"""Tests for Revolut X exchange client."""

import base64
from decimal import Decimal

import httpx
import pytest
import respx
from nacl.signing import SigningKey

from cryptrink.exchange.base import (
    AuthenticationError,
    ExchangeError,
    InsufficientFundsError,
    OrderNotFoundError,
    OrderSide,
    OrderStatus,
    OrderType,
    RateLimitError,
)
from cryptrink.exchange.revolutx import (
    DEFAULT_BASE_URL,
    RevolutXExchange,
)

# For tests, use the same base URL
TEST_BASE_URL = DEFAULT_BASE_URL


@pytest.fixture
def signing_key() -> SigningKey:
    """Generate a test signing key."""
    return SigningKey.generate()


@pytest.fixture
def private_key_base64(signing_key: SigningKey) -> str:
    """Get base64-encoded private key."""
    return base64.b64encode(bytes(signing_key)).decode()


@pytest.fixture
def exchange(private_key_base64: str) -> RevolutXExchange:
    """Create a Revolut X exchange client for testing."""
    return RevolutXExchange(
        api_key="test-api-key",
        private_key_base64=private_key_base64,
        timeout=10.0,
    )


class TestRevolutXExchangeProperties:
    """Tests for exchange properties."""

    def test_name(self, exchange: RevolutXExchange) -> None:
        """Test exchange name property."""
        assert exchange.name == "revolut_x"

    def test_is_sandbox(self, exchange: RevolutXExchange) -> None:
        """Test sandbox property (always False for Revolut X)."""
        assert exchange.is_sandbox is False


class TestRevolutXExchangeConnection:
    """Tests for connection management."""

    @pytest.mark.asyncio
    async def test_connect_creates_client(self, exchange: RevolutXExchange) -> None:
        """Test that connect creates HTTP client."""
        assert exchange._client is None
        await exchange.connect()
        assert exchange._client is not None
        await exchange.close()

    @pytest.mark.asyncio
    async def test_connect_idempotent(self, exchange: RevolutXExchange) -> None:
        """Test that multiple connect calls are safe."""
        await exchange.connect()
        client1 = exchange._client
        await exchange.connect()
        assert exchange._client is client1
        await exchange.close()

    @pytest.mark.asyncio
    async def test_close_clears_client(self, exchange: RevolutXExchange) -> None:
        """Test that close clears HTTP client."""
        await exchange.connect()
        await exchange.close()
        assert exchange._client is None

    @pytest.mark.asyncio
    async def test_context_manager(self, exchange: RevolutXExchange) -> None:
        """Test async context manager."""
        async with exchange:
            assert exchange._client is not None
        assert exchange._client is None

    @pytest.mark.asyncio
    async def test_request_without_connect_raises(self, exchange: RevolutXExchange) -> None:
        """Test that request without connect raises error."""
        with pytest.raises(ExchangeError, match="not connected"):
            await exchange.get_ticker("BTC-EUR")


class TestMarketDataEndpoints:
    """Tests for market data endpoints."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_ticker(self, exchange: RevolutXExchange) -> None:
        """Test getting ticker data."""
        respx.get(f"{TEST_BASE_URL}/trades/all/BTC-EUR").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "p": "42005.00",
                            "q": "1234.56",
                            "tdt": "2024-01-15T10:30:00Z",
                            "tid": "trade1",
                            "s": "BUY",
                        }
                    ]
                },
            )
        )

        async with exchange:
            ticker = await exchange.get_ticker("BTC-EUR")

        assert ticker.symbol == "BTC-EUR"
        assert ticker.last == Decimal("42005.00")

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_ticker_alternate_field_names(self, exchange: RevolutXExchange) -> None:
        """Test ticker parsing with alternate field names."""
        respx.get(f"{TEST_BASE_URL}/trades/all/ETH-EUR").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "p": "42005.00",
                            "q": "1234.56",
                            "tdt": "2024-01-15T10:30:00Z",
                            "tid": "trade2",
                            "s": "SELL",
                        }
                    ]
                },
            )
        )

        async with exchange:
            ticker = await exchange.get_ticker("ETH-EUR")

        assert ticker.last == Decimal("42005.00")

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_orderbook(self, exchange: RevolutXExchange) -> None:
        """Test getting order book."""
        respx.get(f"{TEST_BASE_URL}/public/order-book/BTC-EUR").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "bids": [
                            {"p": "42000.00", "q": "1.5"},
                            {"p": "41990.00", "q": "2.0"},
                        ],
                        "asks": [
                            {"p": "42010.00", "q": "1.0"},
                            {"p": "42020.00", "q": "2.5"},
                        ],
                    }
                },
            )
        )

        async with exchange:
            orderbook = await exchange.get_orderbook("BTC-EUR", depth=20)

        assert orderbook.symbol == "BTC-EUR"
        assert len(orderbook.bids) == 2
        assert len(orderbook.asks) == 2
        assert orderbook.bids[0].price == Decimal("42000.00")
        assert orderbook.bids[0].quantity == Decimal("1.5")
        assert orderbook.asks[0].price == Decimal("42010.00")
        assert orderbook.asks[0].quantity == Decimal("1.0")

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_recent_trades(self, exchange: RevolutXExchange) -> None:
        """Test getting recent trades."""
        respx.get(f"{TEST_BASE_URL}/trades/all/BTC-EUR").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "tid": "trade1",
                            "s": "BUY",
                            "p": "42000.00",
                            "q": "0.5",
                            "tdt": "2024-01-15T10:30:00Z",
                        },
                        {
                            "tid": "trade2",
                            "s": "SELL",
                            "p": "41990.00",
                            "q": "1.0",
                            "tdt": "2024-01-15T10:29:00Z",
                        },
                    ]
                },
            )
        )

        async with exchange:
            trades = await exchange.get_recent_trades("BTC-EUR", limit=100)

        assert len(trades) == 2
        assert trades[0].id == "trade1"
        assert trades[0].side == OrderSide.BUY
        assert trades[0].price == Decimal("42000.00")
        assert trades[0].quantity == Decimal("0.5")
        assert trades[1].id == "trade2"
        assert trades[1].side == OrderSide.SELL
        assert trades[1].quantity == Decimal("1.0")

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_recent_trades_list_response(self, exchange: RevolutXExchange) -> None:
        """Test getting trades when response is a list."""
        respx.get(f"{TEST_BASE_URL}/trades/all/BTC-EUR").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "tid": "trade1",
                            "s": "BUY",
                            "p": "42000.00",
                            "q": "0.5",
                            "tdt": 1705315800000,  # Unix timestamp milliseconds
                        },
                    ]
                },
            )
        )

        async with exchange:
            trades = await exchange.get_recent_trades("BTC-EUR")

        assert len(trades) == 1
        assert trades[0].id == "trade1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_symbols(self, exchange: RevolutXExchange) -> None:
        """Test getting available symbols."""
        respx.get(f"{TEST_BASE_URL}/configuration/pairs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "BTC/EUR": {"base": "BTC", "quote": "EUR"},
                    "ETH/EUR": {"base": "ETH", "quote": "EUR"},
                    "SOL/EUR": {"base": "SOL", "quote": "EUR"},
                },
            )
        )

        async with exchange:
            symbols = await exchange.get_symbols()

        assert len(symbols) == 3
        assert "BTC-EUR" in symbols
        assert "ETH-EUR" in symbols
        assert "SOL-EUR" in symbols

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_symbols_dict_format(self, exchange: RevolutXExchange) -> None:
        """Test getting symbols when response contains dicts."""
        respx.get(f"{TEST_BASE_URL}/configuration/pairs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "BTC/EUR": {"base": "BTC", "quote": "EUR", "status": "active"},
                    "ETH/EUR": {"base": "ETH", "quote": "EUR", "status": "active"},
                },
            )
        )

        async with exchange:
            symbols = await exchange.get_symbols()

        assert len(symbols) == 2
        assert "BTC-EUR" in symbols
        assert "ETH-EUR" in symbols


class TestAccountEndpoints:
    """Tests for account endpoints."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_balances(self, exchange: RevolutXExchange) -> None:
        """Test getting account balances."""
        respx.get(f"{TEST_BASE_URL}/balances").mock(
            return_value=httpx.Response(
                200,
                json={
                    "balances": [
                        {"currency": "EUR", "available": "10000.00", "locked": "500.00"},
                        {
                            "currency": "BTC",
                            "available": "0.5",
                            "reserved": "0.1",
                        },  # alternate field
                    ]
                },
            )
        )

        async with exchange:
            balances = await exchange.get_balances()

        assert "EUR" in balances
        assert "BTC" in balances
        assert balances["EUR"].available == Decimal("10000.00")
        assert balances["EUR"].locked == Decimal("500.00")
        assert balances["BTC"].available == Decimal("0.5")
        assert balances["BTC"].locked == Decimal("0.1")

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_balances_list_response(self, exchange: RevolutXExchange) -> None:
        """Test getting balances when response is a list."""
        respx.get(f"{TEST_BASE_URL}/balances").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"asset": "EUR", "available": "5000.00", "locked": "0"},  # alternate field
                ],
            )
        )

        async with exchange:
            balances = await exchange.get_balances()

        assert "EUR" in balances
        assert balances["EUR"].available == Decimal("5000.00")

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_balance_existing_currency(self, exchange: RevolutXExchange) -> None:
        """Test getting balance for existing currency."""
        respx.get(f"{TEST_BASE_URL}/balances").mock(
            return_value=httpx.Response(
                200,
                json={
                    "balances": [
                        {"currency": "EUR", "available": "10000.00", "locked": "0"},
                    ]
                },
            )
        )

        async with exchange:
            balance = await exchange.get_balance("EUR")

        assert balance.currency == "EUR"
        assert balance.available == Decimal("10000.00")

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_balance_nonexistent_currency(self, exchange: RevolutXExchange) -> None:
        """Test getting balance for nonexistent currency returns zero."""
        respx.get(f"{TEST_BASE_URL}/balances").mock(
            return_value=httpx.Response(
                200,
                json={"balances": []},
            )
        )

        async with exchange:
            balance = await exchange.get_balance("XYZ")

        assert balance.currency == "XYZ"
        assert balance.available == Decimal("0")
        assert balance.locked == Decimal("0")


class TestOrderEndpoints:
    """Tests for order endpoints."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_market_order(self, exchange: RevolutXExchange) -> None:
        """Test creating a market order."""
        respx.post(f"{TEST_BASE_URL}/orders").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "order123",
                    "client_order_id": "client456",
                    "symbol": "BTC/EUR",
                    "side": "buy",
                    "type": "market",
                    "status": "filled",
                    "qty": "0.01",
                    "filled_qty": "0.01",
                    "created_at": "2024-01-15T10:30:00Z",
                    "updated_at": "2024-01-15T10:30:01Z",
                },
            )
        )

        async with exchange:
            order = await exchange.create_order(
                symbol="BTC-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.01"),
            )

        assert order.id == "order123"
        assert order.symbol == "BTC-EUR"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.status == OrderStatus.FILLED
        assert order.quantity == Decimal("0.01")

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_limit_order(self, exchange: RevolutXExchange) -> None:
        """Test creating a limit order."""
        respx.post(f"{TEST_BASE_URL}/orders").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "order789",
                    "symbol": "BTC/EUR",
                    "side": "sell",
                    "type": "limit",
                    "status": "open",
                    "qty": "0.5",
                    "filled_qty": "0",
                    "price": "45000.00",
                    "created_at": "2024-01-15T10:30:00Z",
                    "updated_at": "2024-01-15T10:30:00Z",
                },
            )
        )

        async with exchange:
            order = await exchange.create_order(
                symbol="BTC-EUR",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.5"),
                price=Decimal("45000.00"),
            )

        assert order.id == "order789"
        assert order.order_type == OrderType.LIMIT
        assert order.status == OrderStatus.OPEN
        assert order.price == Decimal("45000.00")

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_stop_order(self, exchange: RevolutXExchange) -> None:
        """Test creating a stop loss order."""
        respx.post(f"{TEST_BASE_URL}/orders").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "order_stop",
                    "symbol": "BTC/EUR",
                    "side": "sell",
                    "type": "stop_loss",
                    "status": "pending",
                    "qty": "0.1",
                    "filled_qty": "0",
                    "stop_price": "40000.00",
                    "created_at": "2024-01-15T10:30:00Z",
                    "updated_at": "2024-01-15T10:30:00Z",
                },
            )
        )

        async with exchange:
            order = await exchange.create_order(
                symbol="BTC-EUR",
                side=OrderSide.SELL,
                order_type=OrderType.STOP_LOSS,
                quantity=Decimal("0.1"),
                stop_price=Decimal("40000.00"),
            )

        assert order.order_type == OrderType.STOP_LOSS
        assert order.stop_price == Decimal("40000.00")
        assert order.status == OrderStatus.PENDING

    @pytest.mark.asyncio
    @respx.mock
    async def test_cancel_order(self, exchange: RevolutXExchange) -> None:
        """Test cancelling an order."""
        respx.delete(f"{TEST_BASE_URL}/orders/order123").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "order123",
                    "symbol": "BTC/EUR",
                    "side": "buy",
                    "type": "limit",
                    "status": "cancelled",
                    "qty": "0.5",
                    "filled_qty": "0",
                    "price": "42000.00",
                    "created_at": "2024-01-15T10:30:00Z",
                    "updated_at": "2024-01-15T10:31:00Z",
                },
            )
        )

        async with exchange:
            order = await exchange.cancel_order("order123", symbol="BTC-EUR")

        assert order.id == "order123"
        assert order.status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_order(self, exchange: RevolutXExchange) -> None:
        """Test getting order by ID."""
        respx.get(f"{TEST_BASE_URL}/orders/order456").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "order456",
                    "symbol": "ETH/EUR",
                    "side": "buy",
                    "type": "limit",
                    "status": "partially_filled",
                    "qty": "2.0",
                    "filled_qty": "1.0",
                    "price": "2500.00",
                    "created_at": "2024-01-15T10:30:00Z",
                    "updated_at": "2024-01-15T10:35:00Z",
                    "trades": [
                        {
                            "id": "trade1",
                            "side": "buy",
                            "price": "2500.00",
                            "qty": "1.0",
                            "fee": "2.50",
                            "fee_currency": "EUR",
                            "timestamp": "2024-01-15T10:32:00Z",
                        }
                    ],
                },
            )
        )

        async with exchange:
            order = await exchange.get_order("order456")

        assert order.id == "order456"
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == Decimal("1.0")
        assert len(order.trades) == 1
        assert order.trades[0].fee == Decimal("2.50")
        assert order.trades[0].fee_currency == "EUR"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_open_orders(self, exchange: RevolutXExchange) -> None:
        """Test getting all open orders."""
        respx.get(f"{TEST_BASE_URL}/orders/active").mock(
            return_value=httpx.Response(
                200,
                json={
                    "orders": [
                        {
                            "id": "order1",
                            "symbol": "BTC/EUR",
                            "side": "buy",
                            "type": "limit",
                            "status": "open",
                            "qty": "0.5",
                            "filled_qty": "0",
                            "price": "42000.00",
                            "created_at": "2024-01-15T10:30:00Z",
                            "updated_at": "2024-01-15T10:30:00Z",
                        },
                        {
                            "id": "order2",
                            "symbol": "ETH/EUR",
                            "side": "sell",
                            "type": "limit",
                            "status": "active",  # alternate status
                            "qty": "2.0",
                            "filled_qty": "0",
                            "price": "2600.00",
                            "created_at": "2024-01-15T10:25:00Z",
                            "updated_at": "2024-01-15T10:25:00Z",
                        },
                    ]
                },
            )
        )

        async with exchange:
            orders = await exchange.get_open_orders()

        assert len(orders) == 2
        assert orders[0].id == "order1"
        assert orders[0].status == OrderStatus.OPEN
        assert orders[1].id == "order2"
        assert orders[1].status == OrderStatus.OPEN  # 'active' maps to OPEN

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_open_orders_with_symbol_filter(self, exchange: RevolutXExchange) -> None:
        """Test getting open orders filtered by symbol."""
        respx.get(f"{TEST_BASE_URL}/orders/active").mock(
            return_value=httpx.Response(
                200,
                json={
                    "orders": [
                        {
                            "id": "order1",
                            "symbol": "BTC/EUR",
                            "side": "buy",
                            "type": "limit",
                            "status": "open",
                            "qty": "0.5",
                            "filled_qty": "0",
                            "price": "42000.00",
                            "created_at": "2024-01-15T10:30:00Z",
                            "updated_at": "2024-01-15T10:30:00Z",
                        },
                    ]
                },
            )
        )

        async with exchange:
            orders = await exchange.get_open_orders(symbol="BTC-EUR")

        assert len(orders) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_order_history(self, exchange: RevolutXExchange) -> None:
        """Test getting order history."""
        respx.get(f"{TEST_BASE_URL}/orders/historical").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "order1",
                            "symbol": "BTC/EUR",
                            "side": "buy",
                            "type": "market",
                            "status": "filled",
                            "qty": "0.5",
                            "filled_qty": "0.5",
                            "created_at": "2024-01-14T10:30:00Z",
                            "updated_at": "2024-01-14T10:30:01Z",
                        },
                        {
                            "id": "order2",
                            "symbol": "BTC/EUR",
                            "side": "sell",
                            "type": "limit",
                            "status": "cancelled",
                            "qty": "0.3",
                            "filled_qty": "0",
                            "price": "45000.00",
                            "created_at": "2024-01-13T10:30:00Z",
                            "updated_at": "2024-01-13T12:00:00Z",
                        },
                    ]
                },
            )
        )

        async with exchange:
            orders = await exchange.get_order_history(symbol="BTC-EUR", limit=50)

        assert len(orders) == 2
        assert orders[0].status == OrderStatus.FILLED
        assert orders[1].status == OrderStatus.CANCELLED


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_authentication_error_401(self, exchange: RevolutXExchange) -> None:
        """Test 401 raises AuthenticationError."""
        respx.get(f"{TEST_BASE_URL}/balances").mock(
            return_value=httpx.Response(
                401,
                json={"message": "Invalid API key"},
            )
        )

        async with exchange:
            with pytest.raises(AuthenticationError, match="Invalid API key"):
                await exchange.get_balances()

    @pytest.mark.asyncio
    @respx.mock
    async def test_authentication_error_403(self, exchange: RevolutXExchange) -> None:
        """Test 403 raises AuthenticationError."""
        respx.get(f"{TEST_BASE_URL}/balances").mock(
            return_value=httpx.Response(
                403,
                json={"message": "Access denied"},
            )
        )

        async with exchange:
            with pytest.raises(AuthenticationError, match="Access denied"):
                await exchange.get_balances()

    @pytest.mark.asyncio
    @respx.mock
    async def test_order_not_found_error(self, exchange: RevolutXExchange) -> None:
        """Test 404 raises OrderNotFoundError."""
        respx.get(f"{TEST_BASE_URL}/orders/nonexistent").mock(
            return_value=httpx.Response(
                404,
                json={"message": "Order not found"},
            )
        )

        async with exchange:
            with pytest.raises(OrderNotFoundError, match="Order not found"):
                await exchange.get_order("nonexistent")

    @pytest.mark.asyncio
    @respx.mock
    async def test_rate_limit_error(self, exchange: RevolutXExchange) -> None:
        """Test 429 raises RateLimitError."""
        respx.get(f"{TEST_BASE_URL}/trades/all/BTC-EUR").mock(
            return_value=httpx.Response(
                429,
                json={"message": "Rate limit exceeded"},
                headers={"Retry-After": "30"},
            )
        )

        async with exchange:
            with pytest.raises(RateLimitError, match="Rate limit exceeded"):
                await exchange.get_ticker("BTC-EUR")

    @pytest.mark.asyncio
    @respx.mock
    async def test_insufficient_funds_error(self, exchange: RevolutXExchange) -> None:
        """Test insufficient funds error."""
        respx.post(f"{TEST_BASE_URL}/orders").mock(
            return_value=httpx.Response(
                400,
                json={"message": "Insufficient balance"},
            )
        )

        async with exchange:
            with pytest.raises(InsufficientFundsError, match="Insufficient"):
                await exchange.create_order(
                    symbol="BTC-EUR",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("1000.0"),
                )

    @pytest.mark.asyncio
    @respx.mock
    async def test_bad_request_error(self, exchange: RevolutXExchange) -> None:
        """Test 400 raises ExchangeError for non-insufficient-funds errors."""
        respx.post(f"{TEST_BASE_URL}/orders").mock(
            return_value=httpx.Response(
                400,
                json={"message": "Invalid order parameters"},
            )
        )

        async with exchange:
            with pytest.raises(ExchangeError, match="Invalid order parameters"):
                await exchange.create_order(
                    symbol="INVALID",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("0.01"),
                )

    @pytest.mark.asyncio
    @respx.mock
    async def test_server_error(self, exchange: RevolutXExchange) -> None:
        """Test 500 raises ExchangeError."""
        respx.get(f"{TEST_BASE_URL}/trades/all/BTC-EUR").mock(
            return_value=httpx.Response(
                500,
                json={"error": "Internal server error"},
            )
        )

        async with exchange:
            with pytest.raises(ExchangeError, match="Internal server error"):
                await exchange.get_ticker("BTC-EUR")


class TestHelperMethods:
    """Tests for helper/parsing methods."""

    def test_parse_order_type(self, exchange: RevolutXExchange) -> None:
        """Test order type parsing."""
        assert exchange._parse_order_type("market") == OrderType.MARKET
        assert exchange._parse_order_type("limit") == OrderType.LIMIT
        assert exchange._parse_order_type("stop_loss") == OrderType.STOP_LOSS
        assert exchange._parse_order_type("stop-loss") == OrderType.STOP_LOSS
        assert exchange._parse_order_type("take_profit") == OrderType.TAKE_PROFIT
        assert exchange._parse_order_type("take-profit") == OrderType.TAKE_PROFIT
        assert exchange._parse_order_type("stop_limit") == OrderType.STOP_LIMIT
        assert exchange._parse_order_type("stop-limit") == OrderType.STOP_LIMIT
        assert exchange._parse_order_type("unknown") == OrderType.LIMIT

    def test_parse_order_status(self, exchange: RevolutXExchange) -> None:
        """Test order status parsing."""
        assert exchange._parse_order_status("pending") == OrderStatus.PENDING
        assert exchange._parse_order_status("new") == OrderStatus.PENDING
        assert exchange._parse_order_status("open") == OrderStatus.OPEN
        assert exchange._parse_order_status("active") == OrderStatus.OPEN
        assert exchange._parse_order_status("partially_filled") == OrderStatus.PARTIALLY_FILLED
        assert exchange._parse_order_status("partial") == OrderStatus.PARTIALLY_FILLED
        assert exchange._parse_order_status("filled") == OrderStatus.FILLED
        assert exchange._parse_order_status("complete") == OrderStatus.FILLED
        assert exchange._parse_order_status("completed") == OrderStatus.FILLED
        assert exchange._parse_order_status("cancelled") == OrderStatus.CANCELLED
        assert exchange._parse_order_status("canceled") == OrderStatus.CANCELLED
        assert exchange._parse_order_status("rejected") == OrderStatus.REJECTED
        assert exchange._parse_order_status("expired") == OrderStatus.EXPIRED
        assert exchange._parse_order_status("unknown") == OrderStatus.OPEN

    def test_convert_order_type(self, exchange: RevolutXExchange) -> None:
        """Test order type conversion to API string."""
        assert exchange._convert_order_type(OrderType.MARKET) == "market"
        assert exchange._convert_order_type(OrderType.LIMIT) == "limit"
        assert exchange._convert_order_type(OrderType.STOP_LOSS) == "stop_loss"
        assert exchange._convert_order_type(OrderType.TAKE_PROFIT) == "take_profit"
        assert exchange._convert_order_type(OrderType.STOP_LIMIT) == "stop_limit"

    def test_parse_timestamp_iso_format(self, exchange: RevolutXExchange) -> None:
        """Test parsing ISO format timestamp."""
        ts = exchange._parse_timestamp("2024-01-15T10:30:00Z")
        assert ts.year == 2024
        assert ts.month == 1
        assert ts.day == 15

    def test_parse_timestamp_unix_seconds(self, exchange: RevolutXExchange) -> None:
        """Test parsing Unix timestamp in seconds."""
        ts = exchange._parse_timestamp(1705315800)
        assert ts.year == 2024

    def test_parse_timestamp_unix_milliseconds(self, exchange: RevolutXExchange) -> None:
        """Test parsing Unix timestamp in milliseconds."""
        ts = exchange._parse_timestamp(1705315800000)
        assert ts.year == 2024

    def test_parse_timestamp_string_unix(self, exchange: RevolutXExchange) -> None:
        """Test parsing string Unix timestamp."""
        ts = exchange._parse_timestamp("1705315800")
        assert ts.year == 2024

    def test_parse_timestamp_empty_returns_now(self, exchange: RevolutXExchange) -> None:
        """Test that empty timestamp returns current time."""
        ts = exchange._parse_timestamp("")
        assert ts.year >= 2024

    def test_parse_order_with_trades(self, exchange: RevolutXExchange) -> None:
        """Test parsing order data with trades."""
        data = {
            "id": "order123",
            "symbol": "BTC/EUR",
            "side": "buy",
            "type": "limit",
            "status": "filled",
            "qty": "1.0",
            "filled_qty": "1.0",
            "price": "42000.00",
            "created_at": "2024-01-15T10:30:00Z",
            "updated_at": "2024-01-15T10:31:00Z",
            "trades": [
                {
                    "id": "trade1",
                    "side": "buy",
                    "price": "42000.00",
                    "qty": "0.5",
                    "fee": "5.00",
                    "fee_currency": "EUR",
                    "timestamp": "2024-01-15T10:30:30Z",
                },
                {
                    "id": "trade2",
                    "side": "buy",
                    "price": "42000.00",
                    "qty": "0.5",
                    "fee": "5.00",
                    "fee_currency": "EUR",
                    "timestamp": "2024-01-15T10:30:45Z",
                },
            ],
        }

        order = exchange._parse_order(data, "BTC-EUR")

        assert order.id == "order123"
        assert order.symbol == "BTC-EUR"
        assert len(order.trades) == 2
        assert order.trades[0].id == "trade1"
        assert order.trades[0].fee == Decimal("5.00")
        assert order.trades[1].id == "trade2"
