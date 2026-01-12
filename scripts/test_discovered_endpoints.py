#!/usr/bin/env python3
"""Test the endpoints discovered from Revolut X API documentation.

Based on documentation at:
https://developer.revolut.com/docs/x-api/revolut-x-crypto-exchange-rest-api

Discovered endpoints:
- GET /v1/orders (active orders)
- GET /public-market-data/order-book/{symbol} (order book)
- DELETE /orders/{order_id} (cancel order)
- Base URL uses /api/1.0/ prefix according to main docs
"""

import asyncio

from cryptrink.core.config import Settings
from cryptrink.exchange.revolutx import RevolutXExchange


async def test_endpoint(
    exchange: RevolutXExchange,
    method: str,
    path: str,
    authenticated: bool = True,
) -> tuple[str, bool, str]:
    """Test a single endpoint.

    Returns:
        Tuple of (path, success, response_preview)
    """
    try:
        response = await exchange._request(method, path, authenticated=authenticated)
        return (path, True, str(response)[:200])
    except Exception as e:
        return (path, False, str(e)[:200])


async def main():
    """Test discovered API endpoints."""
    print("Testing Revolut X API Discovered Endpoints")
    print("=" * 70)

    settings = Settings()
    private_key = settings.revolutx.get_private_key()

    exchange = RevolutXExchange(
        api_key=settings.revolutx.api_key.get_secret_value(),
        private_key_base64=private_key,
        sandbox=settings.revolutx.sandbox,
    )

    async with exchange:
        print(f"\nBase URL: {exchange._base_url}")
        print()

        # Test endpoints discovered from documentation
        test_cases = [
            # Active orders endpoint (from docs)
            ("GET", "/v1/orders", True, "Active orders (from docs)"),
            # Try with /api/1.0 prefix
            ("GET", "/api/1.0/orders", True, "Active orders with /api/1.0 prefix"),
            # Just /orders
            ("GET", "/orders", True, "Active orders without prefix"),
            # Order book (from docs) - requires symbol parameter
            ("GET", "/public-market-data/order-book/BTC-USD", False, "Order book BTC-USD (public)"),
            ("GET", "/public-market-data/order-book/BTC-EUR", False, "Order book BTC-EUR (public)"),
            # Try balances with different prefixes
            ("GET", "/balances", True, "Balances without prefix"),
            ("GET", "/v1/balances", True, "Balances with /v1"),
            ("GET", "/api/1.0/balances", True, "Balances with /api/1.0"),
            # Try symbols/instruments
            ("GET", "/instruments", True, "Instruments (authenticated)"),
            ("GET", "/instruments", False, "Instruments (public)"),
            ("GET", "/symbols", False, "Symbols (public)"),
            ("GET", "/api/1.0/symbols", False, "Symbols with /api/1.0 (public)"),
        ]

        results = []
        for method, path, authenticated, description in test_cases:
            print(f"Testing: {description}")
            print(f"  {method} {path} (auth={authenticated})")
            result = await test_endpoint(exchange, method, path, authenticated)
            results.append((description, *result))

            if result[1]:  # success
                print("  [OK] SUCCESS!")
                print(f"  Response: {result[2]}")
            else:
                print(f"  [FAIL] FAILED: {result[2]}")
            print()

        # Summary
        print("=" * 70)
        print("Summary:")
        successful = [r for r in results if r[2]]
        failed = [r for r in results if not r[2]]

        print(f"\n[OK] Successful endpoints ({len(successful)}):")
        for desc, path, _success, _response in successful:
            print(f"  - {desc}")
            print(f"    {path}")

        print(f"\n[FAIL] Failed endpoints ({len(failed)}):")
        for desc, path, _success, error in failed:
            print(f"  - {desc}")
            print(f"    {path}")
            print(f"    Error: {error[:100]}")


if __name__ == "__main__":
    asyncio.run(main())
