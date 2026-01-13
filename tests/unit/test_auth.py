"""Tests for Ed25519 authentication module."""

import base64

import pytest
from nacl.signing import SigningKey

from cryptrink.exchange.auth import RevolutXAuth, SignedRequest


class TestSignedRequest:
    """Tests for SignedRequest dataclass."""

    def test_to_headers(self) -> None:
        """Test conversion to HTTP headers."""
        signed = SignedRequest(
            timestamp="1704067200000",
            signature="dGVzdC1zaWduYXR1cmU=",
            api_key="test-api-key",
        )

        headers = signed.to_headers()

        assert headers["X-Revx-Api-Key"] == "test-api-key"
        assert headers["X-Revx-Timestamp"] == "1704067200000"
        assert headers["X-Revx-Signature"] == "dGVzdC1zaWduYXR1cmU="


class TestRevolutXAuth:
    """Tests for RevolutXAuth class."""

    @pytest.fixture
    def signing_key(self) -> SigningKey:
        """Generate a test signing key."""
        return SigningKey.generate()

    @pytest.fixture
    def auth(self, signing_key: SigningKey) -> RevolutXAuth:
        """Create an auth instance with test key."""
        private_key_bytes = bytes(signing_key)
        return RevolutXAuth(
            api_key="test-api-key-12345678901234567890123456789012345678901234",
            private_key_bytes=private_key_bytes,
        )

    def test_init_with_valid_key(self, signing_key: SigningKey) -> None:
        """Test initialization with valid key."""
        private_key_bytes = bytes(signing_key)
        auth = RevolutXAuth(
            api_key="test-key",
            private_key_bytes=private_key_bytes,
        )
        assert auth.api_key == "test-key"

    def test_init_with_invalid_key(self) -> None:
        """Test initialization with invalid key raises error."""
        with pytest.raises(ValueError, match="Invalid Ed25519 private key"):
            RevolutXAuth(
                api_key="test-key",
                private_key_bytes=b"invalid-key",
            )

    def test_from_base64_key(self, signing_key: SigningKey) -> None:
        """Test creation from base64-encoded key."""
        private_key_bytes = bytes(signing_key)
        private_key_base64 = base64.b64encode(private_key_bytes).decode()

        auth = RevolutXAuth.from_base64_key(
            api_key="test-key",
            private_key_base64=private_key_base64,
        )

        assert auth.api_key == "test-key"

    def test_sign_request_get(self, auth: RevolutXAuth) -> None:
        """Test signing a GET request."""
        signed = auth.sign_request(
            method="GET",
            path="/api/1.0/ticker",
            query="symbol=BTC/EUR",
            timestamp="1704067200000",
        )

        assert signed.timestamp == "1704067200000"
        assert signed.api_key == auth.api_key
        assert len(signed.signature) > 0
        # Signature should be base64-encoded
        base64.b64decode(signed.signature)

    def test_sign_request_post(self, auth: RevolutXAuth) -> None:
        """Test signing a POST request with body."""
        signed = auth.sign_request(
            method="POST",
            path="/api/1.0/orders",
            body='{"symbol":"BTC/EUR","side":"buy","qty":"0.01"}',
            timestamp="1704067200000",
        )

        assert signed.timestamp == "1704067200000"
        assert len(signed.signature) > 0

    def test_sign_request_generates_timestamp(self, auth: RevolutXAuth) -> None:
        """Test that timestamp is auto-generated if not provided."""
        signed = auth.sign_request(
            method="GET",
            path="/api/1.0/ticker",
        )

        # Timestamp should be a valid millisecond timestamp
        timestamp = int(signed.timestamp)
        assert timestamp > 1700000000000  # After 2023

    def test_sign_request_method_uppercase(self, auth: RevolutXAuth) -> None:
        """Test that method is converted to uppercase."""
        signed1 = auth.sign_request(
            method="get",
            path="/api/1.0/ticker",
            timestamp="1704067200000",
        )
        signed2 = auth.sign_request(
            method="GET",
            path="/api/1.0/ticker",
            timestamp="1704067200000",
        )

        # Same signature for same content
        assert signed1.signature == signed2.signature

    def test_different_requests_different_signatures(self, auth: RevolutXAuth) -> None:
        """Test that different requests produce different signatures."""
        signed1 = auth.sign_request(
            method="GET",
            path="/api/1.0/ticker",
            timestamp="1704067200000",
        )
        signed2 = auth.sign_request(
            method="GET",
            path="/api/1.0/orderbook",
            timestamp="1704067200000",
        )

        assert signed1.signature != signed2.signature

    def test_get_public_key_base64(self, auth: RevolutXAuth) -> None:
        """Test public key extraction."""
        public_key = auth.get_public_key_base64()

        # Should be base64-encoded
        decoded = base64.b64decode(public_key)
        assert len(decoded) == 32  # Ed25519 public key is 32 bytes

    def test_signature_is_verifiable(self, signing_key: SigningKey) -> None:
        """Test that signatures can be verified with the public key."""
        private_key_bytes = bytes(signing_key)
        auth = RevolutXAuth(
            api_key="test-key",
            private_key_bytes=private_key_bytes,
        )

        timestamp = "1704067200000"
        method = "GET"
        path = "/api/1.0/ticker"
        query = "symbol=BTC/EUR"

        signed = auth.sign_request(
            method=method,
            path=path,
            query=query,
            timestamp=timestamp,
        )

        # Reconstruct the message
        message = f"{timestamp}{method.upper()}{path}{query}".encode()

        # Verify the signature
        signature = base64.b64decode(signed.signature)
        verify_key = signing_key.verify_key

        # This should not raise
        verify_key.verify(message, signature)
