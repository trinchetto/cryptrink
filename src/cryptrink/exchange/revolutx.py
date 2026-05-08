"""Revolut X exchange client implementation.

This module provides a complete implementation of the BaseExchange
interface for the Revolut X cryptocurrency exchange.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
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

# Revolut X API base URL
# The base URL already includes the /api/1.0/ prefix
DEFAULT_BASE_URL = "https://revx.revolut.com/api/1.0"


# Map cryptrink string timeframes to the integer minutes the
# /candles/{symbol} endpoint expects in its `interval` query param.
# Supported intervals are exactly enumerated by the Revolut X OpenAPI
# spec — anything outside this list will be rejected by the API with 400.
_TIMEFRAME_TO_INTERVAL_MIN: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "2d": 2880,
    "4d": 5760,
    "1w": 10080,
    "2w": 20160,
    "4w": 40320,
}


def timeframe_to_interval_minutes(timeframe: str) -> int:
    """Translate a cryptrink timeframe string into the API's `interval` integer.

    Raises:
        ValueError: If the timeframe isn't supported by /candles.
    """
    try:
        return _TIMEFRAME_TO_INTERVAL_MIN[timeframe]
    except KeyError as exc:
        supported = ", ".join(_TIMEFRAME_TO_INTERVAL_MIN.keys())
        msg = (
            f"Timeframe {timeframe!r} is not supported by Revolut X /candles. "
            f"Supported: {supported}"
        )
        raise ValueError(msg) from exc


@dataclass(frozen=True)
class PairInfo:
    """Per-pair trading constraints from ``/configuration/pairs``.

    The Revolut X API enforces three minimums simultaneously:
    ``min_order_size`` in the base currency, ``min_order_size_quote`` in
    the quote currency, and the ``base_step`` quantum that quantities must
    be rounded to. An order failing any of them is rejected by the
    exchange. Pre-flighting against this struct catches "your €1 order is
    dust" before it ever leaves cryptrink.
    """

    symbol: str
    base: str
    quote: str
    base_step: Decimal
    quote_step: Decimal
    min_order_size: Decimal
    max_order_size: Decimal
    min_order_size_quote: Decimal
    status: str

    def is_active(self) -> bool:
        """``True`` when the pair currently accepts orders."""
        return self.status.lower() == "active"

    def reject_reason(self, *, quantity: Decimal, notional: Decimal) -> str | None:
        """Return ``None`` if a hypothetical order would clear all minimums.

        Otherwise return a human-readable rejection reason ready to drop
        into the Live tab terminal so the operator sees exactly which
        constraint trips.
        """
        if not self.is_active():
            return f"pair status is {self.status!r} — not currently accepting orders"
        if self.min_order_size > 0 and quantity < self.min_order_size:
            return (
                f"quantity {quantity} {self.base} is below min_order_size "
                f"{self.min_order_size} {self.base}"
            )
        if self.max_order_size > 0 and quantity > self.max_order_size:
            return (
                f"quantity {quantity} {self.base} exceeds max_order_size "
                f"{self.max_order_size} {self.base}"
            )
        if self.min_order_size_quote > 0 and notional < self.min_order_size_quote:
            return (
                f"notional {notional} {self.quote} is below min_order_size_quote "
                f"{self.min_order_size_quote} {self.quote}"
            )
        return None


class RevolutXExchange(BaseExchange):
    """Revolut X cryptocurrency exchange client.

    Implements the BaseExchange interface for trading on Revolut X.

    Example:
        async with RevolutXExchange(
            api_key="your-key",
            private_key_base64="your-private-key",
        ) as exchange:
            ticker = await exchange.get_ticker("BTC-EUR")
            print(f"BTC price: {ticker.last}")
    """

    def __init__(
        self,
        api_key: str,
        private_key_base64: str,
        timeout: float = 30.0,
        base_url: str | None = None,
    ) -> None:
        """Initialize the Revolut X client.

        Args:
            api_key: Revolut X API key.
            private_key_base64: Base64-encoded Ed25519 private key.
            timeout: Request timeout in seconds.
            base_url: Optional custom base URL (overrides default).
        """
        self._api_key = api_key
        self._timeout = timeout
        # Use custom base_url if provided, otherwise use default
        self._base_url = base_url or DEFAULT_BASE_URL

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
    def is_production(self) -> bool:
        """Whether connected to production environment.

        Note: Revolut X only provides a production environment.
        """
        return True

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
        logger.info("exchange_connected", exchange=self.name)

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
        # Note: base_url includes /api/1.0, so endpoint should be relative (e.g., /balances)
        # But signature needs the full path including /api/1.0
        query_string = urlencode(params) if params else ""
        body_string = json.dumps(body, separators=(",", ":")) if body else ""

        # Build full URL for HTTP request
        url = f"{self._base_url}{endpoint}"
        if query_string:
            url = f"{url}?{query_string}"

        # Build full path for signature (must include /api/1.0 prefix)
        signature_path = f"/api/1.0{endpoint}"

        # Rate limiting
        rate_limiter = self._rate_limiter.get_limiter(
            endpoint.split("/")[1] if "/" in endpoint else "default"
        )
        await self._rate_limiter.acquire(endpoint)

        # Sign request if authenticated
        headers: dict[str, str] = {}
        if authenticated:
            signed = self._auth.sign_request(method, signature_path, query_string, body_string)
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
        """Get current ticker for a symbol.

        Note: This uses the all trades endpoint to get the latest trade price.
        """
        # Use all trades endpoint to get ticker-like data
        data = await self._request(
            "GET",
            f"/trades/all/{symbol}",
            authenticated=True,
        )

        # Extract latest trade data to build ticker
        trades = data.get("data", [])
        if not trades:
            # Return zero ticker if no trades
            return Ticker(
                symbol=symbol,
                bid=None,
                ask=None,
                last=Decimal("0"),
                volume_24h=None,
                high_24h=None,
                low_24h=None,
                timestamp=datetime.now(UTC),
            )

        # Get latest trade (first in list)
        latest = trades[0]
        return Ticker(
            symbol=symbol,
            bid=None,  # Not available from trades
            ask=None,  # Not available from trades
            last=Decimal(str(latest.get("p", "0"))),  # 'p' is price
            volume_24h=None,  # Not available from single trade
            high_24h=None,  # Not available from single trade
            low_24h=None,  # Not available from single trade
            timestamp=self._parse_timestamp(latest.get("tdt", "")),  # 'tdt' is trade datetime
        )

    async def get_orderbook(self, symbol: str, depth: int = 20) -> OrderBook:
        """Get order book for a symbol."""
        data = await self._request(
            "GET",
            f"/public/order-book/{symbol}",
            authenticated=False,
        )

        # Parse order book data - 'p' is price, 'q' is quantity
        order_book_data = data.get("data", {})
        bids = tuple(
            OrderBookLevel(
                price=Decimal(str(level.get("p", "0"))),
                quantity=Decimal(str(level.get("q", "0"))),
            )
            for level in order_book_data.get("bids", [])[:depth]
        )

        asks = tuple(
            OrderBookLevel(
                price=Decimal(str(level.get("p", "0"))),
                quantity=Decimal(str(level.get("q", "0"))),
            )
            for level in order_book_data.get("asks", [])[:depth]
        )

        return OrderBook(
            symbol=symbol,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(UTC),
        )

    async def get_recent_trades(self, symbol: str, limit: int = 100) -> list[Trade]:
        """Get recent trades for a symbol."""
        data = await self._request(
            "GET",
            f"/trades/all/{symbol}",
            params={"limit": limit} if limit else None,
            authenticated=True,
        )

        trades = []
        trades_list = data.get("data", [])
        for trade_data in trades_list:
            # API uses: 'tid' for id, 'p' for price, 'q' for quantity, 'tdt' for timestamp, 's' for side
            side_str = str(trade_data.get("s", "BUY")).upper()
            side = OrderSide.BUY if side_str == "BUY" else OrderSide.SELL
            trades.append(
                Trade(
                    id=str(trade_data.get("tid", "")),
                    symbol=symbol,
                    side=side,
                    price=Decimal(str(trade_data.get("p", "0"))),
                    quantity=Decimal(str(trade_data.get("q", "0"))),
                    timestamp=self._parse_timestamp(trade_data.get("tdt", "")),
                )
            )

        return trades

    async def get_symbols(self) -> list[str]:
        """Get list of available trading symbols."""
        data = await self._request("GET", "/configuration/pairs", authenticated=True)

        # API returns dict with symbol keys like "LINK/USD", "BTC/USD" etc
        symbols = []
        if isinstance(data, dict):
            for symbol_key in data:
                # Convert / to - for internal format
                symbols.append(symbol_key.replace("/", "-"))

        return symbols

    async def get_pair_infos(self) -> dict[str, "PairInfo"]:
        """Get every trading pair's metadata, keyed by cryptrink-style symbol.

        ``/configuration/pairs`` returns a dict ``{"BTC/USD": {base, quote,
        base_step, quote_step, min_order_size, max_order_size,
        min_order_size_quote, status}, ...}``. Cryptrink uses the dash form
        (``BTC-USD``) as its canonical symbol identifier, so we normalise on
        the way out.

        Returns:
            Mapping ``{"BTC-USD": PairInfo(...)}``. Pairs whose JSON is
            shaped unexpectedly are silently skipped — better an incomplete
            map than a crashed pre-flight handler.
        """
        data = await self._request("GET", "/configuration/pairs", authenticated=True)
        infos: dict[str, PairInfo] = {}
        if not isinstance(data, dict):
            return infos
        for symbol_key, body in data.items():
            if not isinstance(body, dict):
                continue
            try:
                infos[symbol_key.replace("/", "-")] = PairInfo(
                    symbol=symbol_key.replace("/", "-"),
                    base=str(body.get("base", "")),
                    quote=str(body.get("quote", "")),
                    base_step=Decimal(str(body.get("base_step", "0"))),
                    quote_step=Decimal(str(body.get("quote_step", "0"))),
                    min_order_size=Decimal(str(body.get("min_order_size", "0"))),
                    max_order_size=Decimal(str(body.get("max_order_size", "0"))),
                    min_order_size_quote=Decimal(str(body.get("min_order_size_quote", "0"))),
                    status=str(body.get("status", "")),
                )
            except (ValueError, ArithmeticError):
                # A malformed pair entry shouldn't break the whole lookup.
                logger.warning("pair_info_parse_failed", symbol=symbol_key, body=body)
                continue
        return infos

    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "1h",
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch historical OHLCV candles via ``/candles/{symbol}``.

        The Revolut X API returns up to 5000 candles per request. If
        ``since_ms`` is omitted the response is the most recent 5000
        candles ending at ``until_ms`` (or now). Use :meth:`backfill_candles`
        for ranges that span more than one page.

        Args:
            symbol: Trading pair, e.g. ``"BTC-EUR"``. Cryptrink's dash
                form is sent verbatim — the API accepts both ``BTC-USD``
                and ``BTC/USD`` shapes per the OpenAPI spec.
            timeframe: Cryptrink timeframe string. Translated via
                :func:`timeframe_to_interval_minutes` to the ``interval``
                query param the API expects.
            since_ms: Start timestamp in Unix epoch milliseconds.
                Optional — when omitted the API returns the latest 5000
                candles up to ``until_ms``.
            until_ms: End timestamp in Unix epoch milliseconds. Optional —
                defaults to the current time on the server side.

        Returns:
            List of dicts in the same shape :class:`HistoricalDataFeed`
            consumes: ``{"symbol", "timeframe", "timestamp", "open",
            "high", "low", "close", "volume"}``. ``timestamp`` is the
            candle's start in ms; OHLCV values are :class:`Decimal`.
        """
        interval = timeframe_to_interval_minutes(timeframe)

        params: dict[str, Any] = {"interval": interval}
        if since_ms is not None:
            params["since"] = int(since_ms)
        if until_ms is not None:
            params["until"] = int(until_ms)

        data = await self._request(
            "GET",
            f"/candles/{symbol}",
            params=params,
            authenticated=True,
        )

        candles_list = data.get("data", []) if isinstance(data, dict) else []
        candles: list[dict[str, Any]] = []
        for c in candles_list:
            candles.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timestamp": int(c["start"]),
                    "open": Decimal(str(c["open"])),
                    "high": Decimal(str(c["high"])),
                    "low": Decimal(str(c["low"])),
                    "close": Decimal(str(c["close"])),
                    "volume": Decimal(str(c["volume"])),
                }
            )

        # Some pages can come back unsorted; normalise to ascending order so
        # the caller (and OHLCVRepository) doesn't have to care.
        candles.sort(key=lambda candle: candle["timestamp"])
        return candles

    async def iter_candle_pages(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int | None = None,
        max_pages: int = 50,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Async-iterate pages of candles backwards.

        Each yielded page is the raw response from a single ``/candles``
        call (no ``since_ms`` query param — Revolut X rejects requests
        that would return more than 50,000 rows, so we always let the
        API return its natural 5000-row window ending at ``until_ms``
        and walk the cursor back ourselves).

        The loop stops when (a) a page comes back empty, (b) the
        earliest candle in a page is at or before ``since_ms``, or
        (c) ``max_pages`` is reached. Caller is responsible for
        deduplicating timestamps across pages.

        Args:
            symbol: Trading pair.
            timeframe: Cryptrink timeframe string.
            since_ms: Inclusive lower bound — pagination stops once a
                page reaches at or before this timestamp.
            until_ms: Inclusive upper bound; defaults to now.
            max_pages: Hard cap on the number of HTTP calls the loop
                will issue. Defaults to 50, which covers ~250k candles
                — plenty for typical multi-year backfills at common
                timeframes (e.g. 1h: ~17k/year, so 50 pages * 5000 ≈
                14 years).
        """
        if until_ms is None:
            until_ms = int(datetime.now(UTC).timestamp() * 1000)
        if since_ms >= until_ms:
            return

        cursor = until_ms
        for _ in range(max_pages):
            page = await self.get_candles(
                symbol=symbol,
                timeframe=timeframe,
                until_ms=cursor,
                # since_ms intentionally omitted — see method docstring.
            )
            if not page:
                return
            yield page

            earliest = page[0]["timestamp"]
            if earliest <= since_ms:
                return

            cursor = earliest - 1

    async def backfill_candles(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int | None = None,
        max_pages: int = 50,
    ) -> list[dict[str, Any]]:
        """Convenience wrapper around :meth:`iter_candle_pages`.

        Drains the page iterator, deduplicates candles by timestamp,
        sorts ascending, and clips to ``[since_ms, until_ms]``. Use
        :meth:`iter_candle_pages` directly when you want per-page
        progress (the Data tab does this to stream backfill status).
        """
        if until_ms is None:
            until_ms = int(datetime.now(UTC).timestamp() * 1000)
        if since_ms >= until_ms:
            return []

        seen: set[int] = set()
        collected: list[dict[str, Any]] = []
        async for page in self.iter_candle_pages(
            symbol=symbol,
            timeframe=timeframe,
            since_ms=since_ms,
            until_ms=until_ms,
            max_pages=max_pages,
        ):
            for candle in page:
                ts = candle["timestamp"]
                if ts in seen:
                    continue
                seen.add(ts)
                collected.append(candle)

        collected.sort(key=lambda candle: candle["timestamp"])
        return [c for c in collected if since_ms <= c["timestamp"] <= until_ms]

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
            params["symbols"] = symbol  # Note: API uses 'symbols' not 'symbol'

        data = await self._request("GET", "/orders/historical", params=params)

        orders = []
        orders_list = data.get("data", [])
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
