#!/usr/bin/env python3
"""Test endpoints with /crypto-exchange/ prefix.

The documentation mentioned /api/1.0/crypto-exchange/orders as an example path.
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
    """Test a single endpoint."""
    try:
        response = await exchange._request(method, path, authenticated=authenticated)
        return (path, True, str(response)[:300])
    except Exception as e:
        return (path, False, str(e)[:200])


async def main():
    """Test crypto-exchange prefix endpoints."""
    print("Testing Revolut X API with /crypto-exchange/ prefix")
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

        # Test with /api/1.0/crypto-exchange/ prefix
        test_cases = [
            ("GET", "/api/1.0/crypto-exchange/orders", True, "Orders"),
            ("GET", "/api/1.0/crypto-exchange/orders/active", True, "Active orders"),
            ("GET", "/api/1.0/crypto-exchange/balances", True, "Balances"),
            ("GET", "/api/1.0/crypto-exchange/instruments", True, "Instruments (auth)"),
            ("GET", "/api/1.0/crypto-exchange/instruments", False, "Instruments (public)"),
            ("GET", "/api/1.0/crypto-exchange/symbols", False, "Symbols"),
            ("GET", "/api/1.0/crypto-exchange/ticker", False, "Ticker"),
            ("GET", "/api/1.0/crypto-exchange/markets", False, "Markets"),
            (
                "GET",
                "/api/1.0/crypto-exchange/public-market-data/order-book/BTC-USD",
                False,
                "Order book",
            ),
        ]

        results = []
        for method, path, authenticated, description in test_cases:
            print(f"Testing: {description}")
            print(f"  {method} {path}")
            result = await test_endpoint(exchange, method, path, authenticated)
            results.append((description, *result))

            if result[1]:
                print("  [OK] SUCCESS!")
                print(f"  Response: {result[2]}")
            else:
                print(f"  [FAIL] {result[2]}")
            print()

        # Summary
        print("=" * 70)
        print("Summary:")
        successful = [r for r in results if r[2]]
        print(f"\nSuccessful endpoints: {len(successful)}")
        for desc, path, _success, _response in successful:
            print(f"  - {desc}: {path}")


if __name__ == "__main__":
    asyncio.run(main())
