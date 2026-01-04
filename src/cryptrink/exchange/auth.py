"""Ed25519 authentication for Revolut X API.

This module handles request signing using Ed25519 signatures as required
by the Revolut X API authentication scheme.
"""

import base64
import time
from dataclasses import dataclass

from nacl.signing import SigningKey


@dataclass(frozen=True)
class SignedRequest:
    """Container for signed request headers."""

    timestamp: str
    signature: str
    api_key: str

    def to_headers(self) -> dict[str, str]:
        """Convert to HTTP headers dict."""
        return {
            "X-Revx-Api-Key": self.api_key,
            "X-Revx-Timestamp": self.timestamp,
            "X-Revx-Signature": self.signature,
        }


class RevolutXAuth:
    """Handles Ed25519 signing for Revolut X API requests.

    The Revolut X API requires each request to be signed using Ed25519.
    The signature is computed over a concatenation of:
    - Timestamp (Unix epoch in milliseconds)
    - HTTP Method (uppercase)
    - Request Path (starting with /api)
    - Query String (without the leading ?)
    - Request Body (minified JSON, if present)

    Example:
        auth = RevolutXAuth(api_key="your-key", private_key_bytes=key_bytes)
        signed = auth.sign_request("GET", "/api/1.0/orders/active", query="limit=10")
        headers = signed.to_headers()
    """

    def __init__(self, api_key: str, private_key_bytes: bytes) -> None:
        """Initialize the authenticator.

        Args:
            api_key: The Revolut X API key (64-character string).
            private_key_bytes: Raw Ed25519 private key bytes (32 bytes).

        Raises:
            ValueError: If private key is invalid.
        """
        self.api_key = api_key
        try:
            self._signing_key = SigningKey(private_key_bytes)
        except Exception as e:
            raise ValueError(f"Invalid Ed25519 private key: {e}") from e

    @classmethod
    def from_base64_key(cls, api_key: str, private_key_base64: str) -> "RevolutXAuth":
        """Create authenticator from base64-encoded private key.

        Args:
            api_key: The Revolut X API key.
            private_key_base64: Base64-encoded Ed25519 private key.

        Returns:
            Configured RevolutXAuth instance.
        """
        private_key_bytes = base64.b64decode(private_key_base64)
        return cls(api_key=api_key, private_key_bytes=private_key_bytes)

    @classmethod
    def from_pem_file(cls, api_key: str, pem_path: str) -> "RevolutXAuth":
        """Create authenticator from PEM file.

        Args:
            api_key: The Revolut X API key.
            pem_path: Path to PEM file containing Ed25519 private key.

        Returns:
            Configured RevolutXAuth instance.
        """
        from pathlib import Path

        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization

        pem_data = Path(pem_path).read_bytes()
        private_key_obj = serialization.load_pem_private_key(
            pem_data,
            password=None,
            backend=default_backend(),
        )

        raw_private = private_key_obj.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

        return cls(api_key=api_key, private_key_bytes=raw_private)

    def sign_request(
        self,
        method: str,
        path: str,
        query: str = "",
        body: str = "",
        timestamp: str | None = None,
    ) -> SignedRequest:
        """Sign an API request.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.).
            path: Request path starting with /api.
            query: Query string without leading ? (e.g., "limit=10&offset=0").
            body: Request body as minified JSON string.
            timestamp: Optional timestamp override (for testing).

        Returns:
            SignedRequest with all required auth headers.
        """
        if timestamp is None:
            timestamp = str(int(time.time() * 1000))

        # Construct the message to sign
        # Format: {timestamp}{METHOD}{path}{query}{body}
        message = f"{timestamp}{method.upper()}{path}{query}{body}"
        message_bytes = message.encode("utf-8")

        # Sign the message
        signed = self._signing_key.sign(message_bytes)

        # Base64 encode the signature (not the full signed message)
        signature = base64.b64encode(signed.signature).decode("ascii")

        return SignedRequest(
            timestamp=timestamp,
            signature=signature,
            api_key=self.api_key,
        )

    def get_public_key_base64(self) -> str:
        """Get the public key as base64 string.

        Useful for registering the public key with Revolut X.

        Returns:
            Base64-encoded public key.
        """
        verify_key = self._signing_key.verify_key
        return base64.b64encode(bytes(verify_key)).decode("ascii")
