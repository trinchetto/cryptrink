#!/usr/bin/env python3
"""Diagnostic script to test Revolut X API endpoints.

This script helps discover the correct API endpoint paths by testing common patterns.
"""

import asyncio

from cryptrink.core.config import Settings
from cryptrink.exchange.revolutx import RevolutXExchange


async def test_endpoint(exchange: RevolutXExchange, method: str, path: str) -> tuple[str, int, str]:
    """Test a single endpoint.

    Returns:
        Tuple of (path, status_code, response_preview)
    """
    try:
        response = await exchange._request(method, path, authenticated=False)
        return (path, 200, str(response)[:100])
    except Exception as e:
        # Extract status code from error if possible
        error_msg = str(e)
        if "404" in error_msg or "Not found" in error_msg:
            return (path, 404, "Not Found")
        if "401" in error_msg or "Authentication" in error_msg:
            return (path, 401, "Authentication Required")
        if "403" in error_msg:
            return (path, 403, "Forbidden")
        return (path, 0, str(e)[:100])


async def main():
    """Test various API endpoint patterns."""
    print("Revolut X API Endpoint Discovery")
    print("=" * 60)

    settings = Settings()
    private_key = settings.revolutx.get_private_key()

    exchange = RevolutXExchange(
        api_key=settings.revolutx.api_key.get_secret_value(),
        private_key_base64=private_key,
        sandbox=settings.revolutx.sandbox,
    )

    # Common API path patterns to test
    test_paths = [
        # Root/meta
        "/",
        "/api",
        "/v1",
        "/api/v1",
        # Market data variations
        "/markets",
        "/api/markets",
        "/v1/markets",
        "/api/v1/markets",
        "/symbols",
        "/api/symbols",
        "/v1/symbols",
        "/api/v1/symbols",
        "/instruments",
        "/api/instruments",
        # Crypto specific
        "/crypto",
        "/crypto/markets",
        "/crypto/symbols",
        "/api/crypto/markets",
        # Account
        "/account",
        "/accounts",
        "/api/account",
        "/api/accounts",
        "/v1/accounts",
        "/wallet",
        "/wallets",
        # Orders
        "/orders",
        "/api/orders",
        "/v1/orders",
        "/trades",
        "/api/trades",
    ]

    async with exchange:
        print(f"\nTesting {len(test_paths)} endpoint patterns...")
        print(f"Base URL: {exchange._base_url}")
        print()

        results = []
        for path in test_paths:
            result = await test_endpoint(exchange, "GET", path)
            results.append(result)

            # Print as we go
            status_code = result[1]
            if status_code == 200:
                print(f"[OK] {status_code} {result[0]} - SUCCESS!")
            elif status_code == 401:
                print(f"[AUTH] {status_code} {result[0]} - Requires auth (endpoint exists!)")
            elif status_code == 404:
                print(f"[404] {status_code} {result[0]}")
            else:
                print(f"[ERR] {status_code} {result[0]} - {result[2]}")

        # Summary
        print("\n" + "=" * 60)
        print("Summary:")
        successful = [r for r in results if r[1] == 200]
        auth_required = [r for r in results if r[1] == 401]
        not_found = [r for r in results if r[1] == 404]

        print(f"  Success (200): {len(successful)}")
        print(f"  Auth Required (401): {len(auth_required)}")
        print(f"  Not Found (404): {len(not_found)}")
        print(f"  Other: {len(results) - len(successful) - len(auth_required) - len(not_found)}")

        if successful:
            print("\nWorking endpoints:")
            for path, _, response in successful:
                print(f"  - {path}")
                print(f"    Response: {response}")

        if auth_required:
            print("\nEndpoints requiring authentication (these exist!):")
            for path, _, _ in auth_required:
                print(f"  - {path}")


if __name__ == "__main__":
    asyncio.run(main())
