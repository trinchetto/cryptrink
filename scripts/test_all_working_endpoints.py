#!/usr/bin/env python3
"""Test all working endpoints listed by the user."""

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
        return (path, True, str(response)[:500])
    except Exception as e:
        return (path, False, str(e)[:300])


async def main():
    """Test all working endpoints."""
    print("Testing All Revolut X API Endpoints")
    print("=" * 70)

    settings = Settings()
    private_key = settings.revolutx.get_private_key()

    exchange = RevolutXExchange(
        api_key=settings.revolutx.api_key.get_secret_value(),
        private_key_base64=private_key,
    )

    async with exchange:
        print(f"Base URL: {exchange._base_url}")
        print()

        # Test all endpoints from the list provided
        test_cases = [
            ("GET", "/balances", True, "Get balances"),
            ("GET", "/configuration/currencies", True, "Get currencies"),
            ("GET", "/configuration/pairs", True, "Get pairs"),
            ("GET", "/public/last-trades", False, "Get last trades (no symbol)"),
            ("GET", "/public/last-trades/BTC-USD", False, "Get last trades BTC-USD"),
            ("GET", "/public/order-book/BTC-USD", False, "Get order book BTC-USD"),
            ("GET", "/orders", True, "Get orders"),
            ("GET", "/orders/active", True, "Get active orders"),
            ("GET", "/orders/historical", True, "Get historical orders"),
            ("GET", "/trades/all/BTC-USD", True, "Get all trades BTC-USD"),
            ("GET", "/trades/private/BTC-USD", True, "Get private trades BTC-USD"),
            ("GET", "/order-book/BTC-USD", True, "Get order book BTC-USD (auth)"),
            ("GET", "/candles/BTC-USD", False, "Get candles BTC-USD"),
        ]

        results = []
        for method, path, authenticated, description in test_cases:
            print(f"Testing: {description}")
            print(f"  {method} {path} (auth={authenticated})")
            result = await test_endpoint(exchange, method, path, authenticated)
            results.append((description, *result))

            if result[1]:
                print("  [OK] SUCCESS!")
                print(f"  Response: {result[2][:200]}")
            else:
                error_line = result[2].split("\n")[0]
                print(f"  [FAIL] {error_line[:120]}")
            print()

        # Summary
        print("=" * 70)
        print("Summary:")
        successful = [r for r in results if r[2]]

        print(f"\nWorking endpoints: {len(successful)} out of {len(results)}")
        if successful:
            print("\n" + "=" * 70)
            print("WORKING ENDPOINTS:")
            print("=" * 70)
            for desc, path, _success, response in successful:
                print(f"\n{desc}")
                print(f"  Path: {path}")
                print(f"  Response: {response[:250]}")


if __name__ == "__main__":
    asyncio.run(main())
