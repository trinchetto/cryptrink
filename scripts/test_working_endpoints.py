"""Test the discovered working endpoints."""

import asyncio

from cryptrink.core.config import Settings
from cryptrink.exchange.revolutx import RevolutXExchange


async def main():
    """Test working endpoints."""
    settings = Settings()
    private_key = settings.revolutx.get_private_key()

    exchange = RevolutXExchange(
        api_key=settings.revolutx.api_key.get_secret_value(),
        private_key_base64=private_key,
        sandbox=settings.revolutx.sandbox,
    )

    async with exchange:
        # Test /instruments
        print("Testing /instruments (authenticated)...")
        try:
            data = await exchange._request("GET", "/instruments", authenticated=True)
            print("  SUCCESS! Got response")
            print(f"  Response type: {type(data)}")
            if isinstance(data, dict):
                print(f"  Keys: {list(data.keys())}")
            print(f"  Sample (first 500 chars): {str(data)[:500]}")
            print()
        except Exception as e:
            print(f"  ERROR: {e}")
            print()

        # Test /wallets
        print("Testing /wallets (authenticated)...")
        try:
            data = await exchange._request("GET", "/wallets", authenticated=True)
            print("  SUCCESS! Got response")
            print(f"  Response type: {type(data)}")
            if isinstance(data, dict):
                print(f"  Keys: {list(data.keys())}")
            print(f"  Sample (first 500 chars): {str(data)[:500]}")
            print()
        except Exception as e:
            print(f"  ERROR: {e}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
