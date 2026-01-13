#!/usr/bin/env python3
"""Test endpoints after fixing the URL building bug and adding base_url support."""

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
    """Test with fixed URL building."""
    print("Testing Revolut X API with Fixes")
    print("=" * 70)

    settings = Settings()
    private_key = settings.revolutx.get_private_key()

    # Now passing base_url from configuration
    exchange = RevolutXExchange(
        api_key=settings.revolutx.api_key.get_secret_value(),
        private_key_base64=private_key,
        base_url=settings.revolutx.base_url,
    )

    async with exchange:
        print(f"\nBase URL from config: {settings.revolutx.base_url}")
        print(f"Exchange using: {exchange._base_url}")
        print()

        # Test basic endpoints
        test_cases = [
            # Account/Balance endpoints
            ("GET", "/balances", True, "Get all balances"),
            ("GET", "/accounts", True, "Get accounts"),
            # Market data
            ("GET", "/symbols", False, "Get symbols (public)"),
            ("GET", "/instruments", False, "Get instruments (public)"),
            ("GET", "/markets", False, "Get markets (public)"),
            ("GET", "/ticker", False, "Get ticker (public)"),
            # Orders
            ("GET", "/orders", True, "Get orders"),
            ("GET", "/orders/active", True, "Get active orders"),
            # Public market data with /crypto-exchange/ prefix
            ("GET", "/crypto-exchange/symbols", False, "Crypto Exchange: Symbols"),
            ("GET", "/crypto-exchange/balances", True, "Crypto Exchange: Balances"),
        ]

        results = []
        for method, path, authenticated, description in test_cases:
            print(f"Testing: {description}")
            print(f"  {method} {path}")
            result = await test_endpoint(exchange, method, path, authenticated)
            results.append((description, *result))

            if result[1]:
                print("  [OK] SUCCESS!")
                print(f"  Response preview: {result[2][:200]}")
            else:
                print(f"  [FAIL] {result[2][:150]}")
            print()

        # Summary
        print("=" * 70)
        print("Summary:")
        successful = [r for r in results if r[2]]
        print(f"\nSuccessful endpoints: {len(successful)} out of {len(results)}")
        if successful:
            print("\nWorking endpoints:")
            for desc, path, _success, _response in successful:
                print(f"  - {desc}")
                print(f"    Path: {path}")
                print()


if __name__ == "__main__":
    asyncio.run(main())
