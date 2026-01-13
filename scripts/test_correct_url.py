#!/usr/bin/env python3
"""Test Revolut X API with the correct production URL."""

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
    """Test with correct production URL."""
    print("Testing Revolut X API with Correct Production URL")
    print("=" * 70)

    settings = Settings()
    private_key = settings.revolutx.get_private_key()

    exchange = RevolutXExchange(
        api_key=settings.revolutx.api_key.get_secret_value(),
        private_key_base64=private_key,
        base_url=settings.revolutx.base_url,
    )

    async with exchange:
        print(f"\nBase URL: {exchange._base_url}")
        print()

        # Test basic endpoints (paths should be relative to /api/1.0)
        test_cases = [
            # Account/Balance
            ("GET", "/balances", True, "Get all balances"),
            ("GET", "/accounts", True, "Get accounts"),
            # Instruments/Markets
            ("GET", "/instruments", False, "Get instruments (public)"),
            ("GET", "/markets", False, "Get markets (public)"),
            ("GET", "/symbols", False, "Get symbols (public)"),
            # Orders
            ("GET", "/orders", True, "Get all orders"),
            ("GET", "/orders/active", True, "Get active orders"),
            # Market data
            ("GET", "/ticker", False, "Get ticker"),
            ("GET", "/trades", False, "Get recent trades"),
            ("GET", "/orderbook", False, "Get order book"),
        ]

        results = []
        for method, path, authenticated, description in test_cases:
            print(f"Testing: {description}")
            print(f"  {method} {path}")
            result = await test_endpoint(exchange, method, path, authenticated)
            results.append((description, *result))

            if result[1]:
                print("  [OK] SUCCESS!")
                print(f"  Response: {result[2][:200]}")
            else:
                print(f"  [FAIL] {result[2][:150]}")
            print()

        # Summary
        print("=" * 70)
        print("Summary:")
        successful = [r for r in results if r[2]]
        failed = [r for r in results if not r[2]]

        print(f"\nSuccessful endpoints: {len(successful)} out of {len(results)}")
        if successful:
            print("\n[OK] Working endpoints:")
            for desc, path, _success, response in successful:
                print(f"  - {desc}")
                print(f"    Path: {path}")
                print(f"    Response preview: {response[:150]}")
                print()

        if failed and len(failed) < len(results):
            print("\n[FAIL] Failed endpoints:")
            for desc, path, _success, error in failed:
                print(f"  - {desc}: {path}")
                print(f"    Error: {error[:100]}")


if __name__ == "__main__":
    asyncio.run(main())
