"""Revolut X exchange client implementation.

This module provides a complete implementation of the BaseExchange
interface for the Revolut X cryptocurrency exchange.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from cryptrink.core.logging import get_logger
from cryptrink.exchange.auth import RevolutXAuth
from cryptrink.exchange.base import (
    AuthenticationError,
    Balance,
    BaseExchange,
    ExchangeError,
    InsufficientFundsError,
    Order,
    OrderBook,
    OrderBookLevel,
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
)

logger = get_logger(__name__)

# Revolut X API base URLs
SANDBOX_BASE_URL = "https://sandbox-x.revolut.com/api/1.0"
PRODUCTION_BASE_URL = "https://x.revolut.com/api/1.0"


class RevolutXExchange(BaseExchange):
    """Revolut X cryptocurrency exchange client.

    Implements the BaseExchange interface for trading on Revolut X.
    Supports both sandbox (testing) and production environments.

    Example:
        async with RevolutXExchange(
            api_key="your-key",
            private_key_base64="your-private-key",
            sandbox=True,
        ) as exchange:
            ticker = await exchange.get_ticker("BTC-EUR")
            print(f"BTC price: {ticker.last}")
    """

    def __init__(
        self,
        api_key: str,
        private_key_base64: str,
        sandbox: bool = True,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the Revolut X client.

        Args:
            api_key: Revolut X API key.
            private_key_base64: Base64-encoded Ed25519 private key.
            sandbox: Use sandbox environment if True.
            timeout: Request timeout in seconds.
        """
        self._api_key = api_key
        self._sandbox = sandbox
        self._timeout = timeout
        self._base_url = SANDBOX_BASE_URL if sandbox else PRODUCTION_BASE_URL

        # Initialize authentication
        self._auth = RevolutXAuth.from_base64_key(api_key, private_key_base64)

        # Initialize HTTP client (created in connect())
        self._client: httpx.AsyncClient | None = None

        # Initialize rate limiters
        self._rate_limiter = EndpointRateLimiter(
            default_config=RateLimitConfig(
                max_requests=100,
                window_seconds=60.0,
                max_retries=3,
            )
        )

        # Configure stricter limits for trading endpoints
        self._rate_limiter.configure_endpoint(
            "orders",
            RateLimitConfig(max_requests=30, window_seconds=60.0),
        )

    @property
    def name(self) -> str:
        """Exchange name."""
        return "revolut_x"

    @property
    def is_sandbox(self) -> bool:
        """Whether using sandbox environment."""
        return self._sandbox

    async def connect(self) -> None:
        """Establish connection to the exchange."""
        if self._client is not None:
            return

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        logger.info("exchange_connected", exchange=self.name, sandbox=self._sandbox)

    async def close(self) -> None:
        """Close connection to the exchange."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("exchange_disconnected", exchange=self.name)

    def _ensure_connected(self) -> httpx.AsyncClient:
        """Ensure client is connected and return it."""
        if self._client is None:
            raise ExchangeError("Exchange not connected. Call connect() first.")
        return self._client

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        """Make an API request.

        Args:
            method: HTTP method.
            endpoint: API endpoint (without base URL).
            params: Query parameters.
            body: Request body.
            authenticated: Whether to sign the request.

        Returns:
            Parsed JSON response.

        Raises:
            ExchangeError: On API errors.
        """
        client = self._ensure_connected()

        # Build path and query
        path = f"/api/1.0{endpoint}"
        query_string = urlencode(params) if params else ""
        body_string = json.dumps(body, separators=(",", ":")) if body else ""

        # Build full URL
        url = f"{self._base_url}{endpoint}"
        if query_string:
            url = f"{url}?{query_string}"

        # Rate limiting
        rate_limiter = self._rate_limiter.get_limiter(
            endpoint.split("/")[1] if "/" in endpoint else "default"
        )
        await self._rate_limiter.acquire(endpoint)

        # Sign request if authenticated
        headers: dict[str, str] = {}
        if authenticated:
            signed = self._auth.sign_request(method, path, query_string, body_string)
            headers.update(signed.to_headers())

        # Make request with retries
        attempt = 0
        last_error: Exception | None = None

        while rate_limiter.should_retry(attempt):
            try:
                logger.debug(
                    "api_request",
                    method=method,
                    endpoint=endpoint,
                    attempt=attempt + 1,
                )

                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    content=body_string if body_string else None,
                )

                # Handle response
                return await self._handle_response(response)

            except httpx.TimeoutException as e:
                last_error = ExchangeError(f"Request timeout: {e}")
                attempt += 1
                if rate_limiter.should_retry(attempt):
                    delay = rate_limiter.calculate_backoff_delay(attempt)
                    logger.warning("request_retry", error=str(e), delay=delay)
                    import asyncio

                    await asyncio.sleep(delay)

            except httpx.RequestError as e:
                last_error = ExchangeError(f"Request failed: {e}")
                attempt += 1
                if rate_limiter.should_retry(attempt):
                    delay = rate_limiter.calculate_backoff_delay(attempt)
                    logger.warning("request_retry", error=str(e), delay=delay)
                    import asyncio

                    await asyncio.sleep(delay)

            except RateLimitError as e:
                last_error = e
                attempt += 1
                if rate_limiter.should_retry(attempt):
                    delay = rate_limiter.calculate_backoff_delay(attempt, e.retry_after)
                    logger.warning("rate_limit_retry", error=str(e), delay=delay)
                    import asyncio

                    await asyncio.sleep(delay)

        if last_error:
            raise last_error
        raise ExchangeError("Request failed after retries")

    async def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle API response.

        Args:
            response: HTTP response.

        Returns:
            Parsed JSON body.

        Raises:
            Various ExchangeError subclasses based on status code.
        """
        # Parse response body
        try:
            raw_data = response.json()
            # Handle both dict and list responses
            if isinstance(raw_data, list):
                data: dict[str, Any] = {"data": raw_data}
            else:
                data = dict(raw_data)
        except json.JSONDecodeError:
            data = {"raw": response.text}

        # Success
        if 200 <= response.status_code < 300:
            return data

        # Error handling
        error_message = data.get("message", data.get("error", str(data)))

        if response.status_code == 401:
            raise AuthenticationError(f"Authentication failed: {error_message}")

        if response.status_code == 403:
            raise AuthenticationError(f"Access forbidden: {error_message}")

        if response.status_code == 404:
            raise OrderNotFoundError(f"Not found: {error_message}")

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            retry_seconds = float(retry_after) if retry_after else None
            raise RateLimitError(f"Rate limit exceeded: {error_message}", retry_seconds)

        if response.status_code == 400:
            if "insufficient" in error_message.lower():
                raise InsufficientFundsError(error_message)
            raise ExchangeError(f"Bad request: {error_message}")

        raise ExchangeError(f"API error ({response.status_code}): {error_message}")

    # -------------------------------------------------------------------------
    # Market Data Methods
    # -------------------------------------------------------------------------

    async def get_ticker(self, symbol: str) -> Ticker:
        """Get current ticker for a symbol."""
        # Convert symbol format: BTC-EUR -> BTC/EUR
        api_symbol = symbol.replace("-", "/")

        data = await self._request(
            "GET",
            "/ticker",
            params={"symbol": api_symbol},
            authenticated=False,
        )

        return Ticker(
            symbol=symbol,
            bid=Decimal(str(data.get("bid", "0"))),
            ask=Decimal(str(data.get("ask", "0"))),
            last=Decimal(str(data.get("last", data.get("price", "0")))),
            volume_24h=Decimal(str(data.get("volume", data.get("volume_24h", "0")))),
            high_24h=Decimal(str(data.get("high", data.get("high_24h", "0")))),
            low_24h=Decimal(str(data.get("low", data.get("low_24h", "0")))),
            timestamp=datetime.now(UTC),
        )

    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """Get order book for a symbol."""
        api_symbol = symbol.replace("-", "/")

        data = await self._request(
            "GET",
            "/orderbook",
            params={"symbol": api_symbol, "depth": depth},
            authenticated=False,
        )

        bids = tuple(
            OrderBookLevel(
                price=Decimal(str(level[0])),
                quantity=Decimal(str(level[1])),
            )
            for level in data.get("bids", [])
        )

        asks = tuple(
            OrderBookLevel(
                price=Decimal(str(level[0])),
                quantity=Decimal(str(level[1])),
            )
            for level in data.get("asks", [])
        )

        return OrderBook(
            symbol=symbol,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(UTC),
        )

    async def get_recent_trades(self, symbol: str, limit: int = 100) -> list[Trade]:
        """Get recent trades for a symbol."""
        api_symbol = symbol.replace("-", "/")

        data = await self._request(
            "GET",
            "/trades",
            params={"symbol": api_symbol, "limit": limit},
            authenticated=False,
        )

        trades = []
        trades_list = data.get("trades") or data.get("data") or []
        for trade_data in trades_list:
            trades.append(
                Trade(
                    id=str(trade_data.get("id", "")),
                    symbol=symbol,
                    side=OrderSide.BUY
                    if trade_data.get("side", "").lower() == "buy"
                    else OrderSide.SELL,
                    price=Decimal(str(trade_data.get("price", "0"))),
                    quantity=Decimal(str(trade_data.get("qty", trade_data.get("quantity", "0")))),
                    timestamp=self._parse_timestamp(
                        trade_data.get("timestamp", trade_data.get("created_at", ""))
                    ),
                )
            )

        return trades

    async def get_symbols(self) -> list[str]:
        """Get list of available trading symbols."""
        data = await self._request("GET", "/symbols", authenticated=False)

        symbols = []
        symbols_list = data.get("symbols") or data.get("data") or []
        for symbol_data in symbols_list:
            if isinstance(symbol_data, str):
                # Convert BTC/EUR -> BTC-EUR
                symbols.append(symbol_data.replace("/", "-"))
            elif isinstance(symbol_data, dict):
                symbol = symbol_data.get("symbol") or symbol_data.get("name") or ""
                symbols.append(symbol.replace("/", "-"))

        return symbols

    # -------------------------------------------------------------------------
    # Account Methods
    # -------------------------------------------------------------------------

    async def get_balances(self) -> dict[str, Balance]:
        """Get all account balances."""
        data = await self._request("GET", "/balances")

        balances = {}
        balances_list = data.get("balances") or data.get("data") or []
        for balance_data in balances_list:
            currency = balance_data.get("currency", balance_data.get("asset", ""))
            balances[currency] = Balance(
                currency=currency,
                available=Decimal(str(balance_data.get("available", "0"))),
                locked=Decimal(str(balance_data.get("locked", balance_data.get("reserved", "0")))),
            )

        return balances

    async def get_balance(self, currency: str) -> Balance:
        """Get balance for a specific currency."""
        balances = await self.get_balances()

        if currency not in balances:
            return Balance(currency=currency, available=Decimal("0"), locked=Decimal("0"))

        return balances[currency]

    # -------------------------------------------------------------------------
    # Order Methods
    # -------------------------------------------------------------------------

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
        """Create a new order."""
        api_symbol = symbol.replace("-", "/")

        body: dict[str, Any] = {
            "symbol": api_symbol,
            "side": side.value,
            "type": self._convert_order_type(order_type),
            "qty": str(quantity),
        }

        if price is not None and order_type != OrderType.MARKET:
            body["price"] = str(price)

        if stop_price is not None:
            body["stop_price"] = str(stop_price)

        if client_order_id:
            body["client_order_id"] = client_order_id

        data = await self._request("POST", "/orders", body=body)

        return self._parse_order(data, symbol)

    async def cancel_order(self, order_id: str, symbol: str | None = None) -> Order:
        """Cancel an open order."""
        data = await self._request("DELETE", f"/orders/{order_id}")
        return self._parse_order(data, symbol or "")

    async def get_order(self, order_id: str, symbol: str | None = None) -> Order:
        """Get order by ID."""
        data = await self._request("GET", f"/orders/{order_id}")
        return self._parse_order(data, symbol or "")

    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        """Get all open orders."""
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.replace("-", "/")

        data = await self._request("GET", "/orders/active", params=params if params else None)

        orders = []
        orders_list = data.get("orders") or data.get("data") or []
        for order_data in orders_list:
            orders.append(self._parse_order(order_data, symbol or ""))

        return orders

    async def get_order_history(
        self,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[Order]:
        """Get order history."""
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol.replace("-", "/")

        data = await self._request("GET", "/orders/history", params=params)

        orders = []
        orders_list = data.get("orders") or data.get("data") or []
        for order_data in orders_list:
            orders.append(self._parse_order(order_data, symbol or ""))

        return orders

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _parse_order(self, data: dict[str, Any], default_symbol: str) -> Order:
        """Parse order data from API response."""
        symbol = data.get("symbol", default_symbol).replace("/", "-")

        # Parse trades if present
        trades = tuple(
            Trade(
                id=str(t.get("id", "")),
                symbol=symbol,
                side=OrderSide.BUY if t.get("side", "").lower() == "buy" else OrderSide.SELL,
                price=Decimal(str(t.get("price", "0"))),
                quantity=Decimal(str(t.get("qty", t.get("quantity", "0")))),
                timestamp=self._parse_timestamp(t.get("timestamp", "")),
                fee=Decimal(str(t.get("fee", "0"))),
                fee_currency=t.get("fee_currency", ""),
            )
            for t in data.get("trades", [])
        )

        return Order(
            id=str(data.get("id", data.get("order_id", ""))),
            client_order_id=str(data.get("client_order_id", "")),
            symbol=symbol,
            side=OrderSide.BUY if data.get("side", "").lower() == "buy" else OrderSide.SELL,
            order_type=self._parse_order_type(data.get("type", "limit")),
            status=self._parse_order_status(data.get("status", "open")),
            quantity=Decimal(str(data.get("qty", data.get("quantity", "0")))),
            filled_quantity=Decimal(str(data.get("filled_qty", data.get("filled_quantity", "0")))),
            price=Decimal(str(data.get("price", "0"))) if data.get("price") else None,
            stop_price=Decimal(str(data.get("stop_price", "0")))
            if data.get("stop_price")
            else None,
            created_at=self._parse_timestamp(data.get("created_at", data.get("timestamp", ""))),
            updated_at=self._parse_timestamp(data.get("updated_at", data.get("timestamp", ""))),
            trades=trades,
        )

    def _parse_timestamp(self, timestamp: str | int | float) -> datetime:
        """Parse timestamp from various formats."""
        if not timestamp:
            return datetime.now(UTC)

        if isinstance(timestamp, int | float):
            # Unix timestamp (seconds or milliseconds)
            if timestamp > 1e12:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp, tz=UTC)

        if isinstance(timestamp, str):
            # ISO format or Unix timestamp string
            try:
                return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                try:
                    ts = float(timestamp)
                    if ts > 1e12:
                        ts = ts / 1000
                    return datetime.fromtimestamp(ts, tz=UTC)
                except ValueError:
                    pass

        return datetime.now(UTC)

    def _convert_order_type(self, order_type: OrderType) -> str:
        """Convert OrderType to API string."""
        mapping = {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP_LOSS: "stop_loss",
            OrderType.TAKE_PROFIT: "take_profit",
            OrderType.STOP_LIMIT: "stop_limit",
        }
        return mapping.get(order_type, "limit")

    def _parse_order_type(self, type_str: str) -> OrderType:
        """Parse order type from API string."""
        mapping = {
            "market": OrderType.MARKET,
            "limit": OrderType.LIMIT,
            "stop_loss": OrderType.STOP_LOSS,
            "stop-loss": OrderType.STOP_LOSS,
            "take_profit": OrderType.TAKE_PROFIT,
            "take-profit": OrderType.TAKE_PROFIT,
            "stop_limit": OrderType.STOP_LIMIT,
            "stop-limit": OrderType.STOP_LIMIT,
        }
        return mapping.get(type_str.lower(), OrderType.LIMIT)

    def _parse_order_status(self, status_str: str) -> OrderStatus:
        """Parse order status from API string."""
        mapping = {
            "pending": OrderStatus.PENDING,
            "new": OrderStatus.PENDING,
            "open": OrderStatus.OPEN,
            "active": OrderStatus.OPEN,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "partial": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
            "complete": OrderStatus.FILLED,
            "completed": OrderStatus.FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "canceled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
            "expired": OrderStatus.EXPIRED,
        }
        return mapping.get(status_str.lower(), OrderStatus.OPEN)
