#!/usr/bin/env python3
"""Test all endpoints with authentication enabled."""

import asyncio

from cryptrink.core.config import Settings
from cryptrink.exchange.revolutx import RevolutXExchange


async def test_endpoint(
    exchange: RevolutXExchange,
    method: str,
    path: str,
) -> tuple[str, bool, str]:
    """Test a single endpoint with authentication."""
    try:
        response = await exchange._request(method, path, authenticated=True)
        return (path, True, str(response)[:500])
    except Exception as e:
        return (path, False, str(e)[:300])


async def main():
    """Test all endpoints with authentication."""
    print("Testing Revolut X API Endpoints (All Authenticated)")
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

        # Test various endpoint patterns
        test_cases = [
            # Working endpoints
            ("GET", "/balances", "Get balances"),
            ("GET", "/orders/active", "Get active orders"),
            # Try market data with auth
            ("GET", "/instruments", "Get instruments"),
            ("GET", "/markets", "Get markets"),
            ("GET", "/symbols", "Get symbols"),
            ("GET", "/ticker", "Get ticker"),
            # Try different variations for orders
            ("GET", "/orders", "Get all orders"),
            ("GET", "/orders/history", "Get order history"),
            # Try trades
            ("GET", "/trades", "Get trades"),
            ("GET", "/trades/history", "Get trade history"),
            # Configuration
            ("GET", "/configuration", "Get configuration"),
            ("GET", "/config", "Get config"),
            # Market data variations
            ("GET", "/market-data/instruments", "Market data: instruments"),
            ("GET", "/public-market-data/instruments", "Public market data: instruments"),
        ]

        results = []
        for method, path, description in test_cases:
            print(f"Testing: {description}")
            print(f"  {method} {path}")
            result = await test_endpoint(exchange, method, path)
            results.append((description, *result))

            if result[1]:
                print("  [OK] SUCCESS!")
                print(f"  Response: {result[2][:200]}")
            else:
                # Only show first line of error
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
                print(f"  Response: {response[:300]}")
                print()


if __name__ == "__main__":
    asyncio.run(main())
