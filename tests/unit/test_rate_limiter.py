"""Tests for rate limiting module."""

import asyncio

import pytest

from cryptrink.exchange.rate_limiter import (
    EndpointRateLimiter,
    RateLimitConfig,
    RateLimiter,
    with_retry,
)


class TestRateLimitConfig:
    """Tests for RateLimitConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = RateLimitConfig()

        assert config.max_requests == 100
        assert config.window_seconds == 60.0
        assert config.max_retries == 5
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.jitter_factor == 0.1

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = RateLimitConfig(
            max_requests=50,
            window_seconds=30.0,
            max_retries=3,
        )

        assert config.max_requests == 50
        assert config.window_seconds == 30.0
        assert config.max_retries == 3


class TestRateLimiter:
    """Tests for RateLimiter class."""

    @pytest.fixture
    def limiter(self) -> RateLimiter:
        """Create a rate limiter with small limits for testing."""
        config = RateLimitConfig(
            max_requests=3,
            window_seconds=1.0,
            max_retries=3,
            base_delay=0.1,
            max_delay=1.0,
            jitter_factor=0.0,  # No jitter for predictable tests
        )
        return RateLimiter(config=config)

    @pytest.mark.asyncio
    async def test_acquire_under_limit(self, limiter: RateLimiter) -> None:
        """Test acquiring when under the rate limit."""
        # Should not block
        await limiter.acquire()
        await limiter.acquire()

        assert limiter.get_remaining_requests() == 1

    @pytest.mark.asyncio
    async def test_acquire_at_limit_waits(self, limiter: RateLimiter) -> None:
        """Test that acquiring at limit waits for window to expire."""
        # Fill up the limit
        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()

        assert limiter.get_remaining_requests() == 0

        # Next acquire should wait (but we use small window)
        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start

        # Should have waited approximately 1 second
        assert elapsed >= 0.9

    def test_get_remaining_requests(self, limiter: RateLimiter) -> None:
        """Test remaining requests calculation."""
        assert limiter.get_remaining_requests() == 3

    def test_calculate_backoff_delay_exponential(self, limiter: RateLimiter) -> None:
        """Test exponential backoff calculation."""
        delay0 = limiter.calculate_backoff_delay(0)
        delay1 = limiter.calculate_backoff_delay(1)
        delay2 = limiter.calculate_backoff_delay(2)

        # With base_delay=0.1 and jitter=0:
        # attempt 0: 0.1 * 2^0 = 0.1
        # attempt 1: 0.1 * 2^1 = 0.2
        # attempt 2: 0.1 * 2^2 = 0.4
        assert delay0 == pytest.approx(0.1)
        assert delay1 == pytest.approx(0.2)
        assert delay2 == pytest.approx(0.4)

    def test_calculate_backoff_delay_max_cap(self, limiter: RateLimiter) -> None:
        """Test that backoff is capped at max_delay."""
        # Large attempt number should be capped
        delay = limiter.calculate_backoff_delay(100)
        assert delay == limiter.config.max_delay

    def test_calculate_backoff_delay_with_retry_after(self, limiter: RateLimiter) -> None:
        """Test that retry_after is used when provided."""
        # retry_after=0.5 is less than max_delay=1.0, so it should be used
        delay = limiter.calculate_backoff_delay(0, retry_after=0.5)
        assert delay == pytest.approx(0.5)

    def test_calculate_backoff_delay_retry_after_capped(self, limiter: RateLimiter) -> None:
        """Test that retry_after is capped at max_delay."""
        delay = limiter.calculate_backoff_delay(0, retry_after=100.0)
        assert delay == limiter.config.max_delay

    def test_should_retry(self, limiter: RateLimiter) -> None:
        """Test retry decision logic."""
        assert limiter.should_retry(0) is True
        assert limiter.should_retry(1) is True
        assert limiter.should_retry(2) is True
        assert limiter.should_retry(3) is False  # max_retries=3
        assert limiter.should_retry(4) is False


class TestEndpointRateLimiter:
    """Tests for EndpointRateLimiter class."""

    @pytest.fixture
    def endpoint_limiter(self) -> EndpointRateLimiter:
        """Create an endpoint rate limiter."""
        return EndpointRateLimiter(
            default_config=RateLimitConfig(max_requests=10)
        )

    def test_default_limiter_for_unknown_endpoint(
        self, endpoint_limiter: EndpointRateLimiter
    ) -> None:
        """Test that unknown endpoints get default limiter."""
        limiter = endpoint_limiter.get_limiter("unknown")
        assert limiter.config.max_requests == 10

    def test_configure_endpoint(self, endpoint_limiter: EndpointRateLimiter) -> None:
        """Test configuring specific endpoint."""
        endpoint_limiter.configure_endpoint(
            "orders",
            RateLimitConfig(max_requests=5),
        )

        limiter = endpoint_limiter.get_limiter("orders")
        assert limiter.config.max_requests == 5

    @pytest.mark.asyncio
    async def test_acquire_creates_limiter(
        self, endpoint_limiter: EndpointRateLimiter
    ) -> None:
        """Test that acquire creates limiter for new endpoint."""
        await endpoint_limiter.acquire("new_endpoint")
        limiter = endpoint_limiter.get_limiter("new_endpoint")
        assert limiter is not None


class TestWithRetry:
    """Tests for with_retry function."""

    @pytest.fixture
    def limiter(self) -> RateLimiter:
        """Create a rate limiter for retry testing."""
        return RateLimiter(
            config=RateLimitConfig(
                max_retries=3,
                base_delay=0.01,  # Fast retries for testing
                jitter_factor=0.0,
            )
        )

    @pytest.mark.asyncio
    async def test_success_on_first_try(self, limiter: RateLimiter) -> None:
        """Test successful execution on first attempt."""
        call_count = 0

        async def success_func() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        result = await with_retry(success_func, limiter)

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, limiter: RateLimiter) -> None:
        """Test retry on transient failure."""
        call_count = 0

        async def fail_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Transient error")
            return "success"

        result = await with_retry(
            fail_then_succeed,
            limiter,
            retryable_exceptions=(ValueError,),
        )

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausted_retries(self, limiter: RateLimiter) -> None:
        """Test that retries are eventually exhausted."""
        call_count = 0

        async def always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("Permanent error")

        with pytest.raises(ValueError, match="Permanent error"):
            await with_retry(
                always_fail,
                limiter,
                retryable_exceptions=(ValueError,),
            )

        # Should have tried max_retries + 1 times
        assert call_count == limiter.config.max_retries + 1

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self, limiter: RateLimiter) -> None:
        """Test that non-retryable exceptions are raised immediately."""
        call_count = 0

        async def raise_type_error() -> str:
            nonlocal call_count
            call_count += 1
            raise TypeError("Not retryable")

        with pytest.raises(TypeError, match="Not retryable"):
            await with_retry(
                raise_type_error,
                limiter,
                retryable_exceptions=(ValueError,),  # TypeError not included
            )

        assert call_count == 1  # No retries
