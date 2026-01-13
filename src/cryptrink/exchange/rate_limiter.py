"""Rate limiting for API requests with exponential backoff.

This module provides rate limiting functionality to prevent exceeding
API rate limits and implements retry logic with exponential backoff.
"""

import asyncio
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from cryptrink.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    # Maximum requests per time window
    max_requests: int = 100

    # Time window in seconds
    window_seconds: float = 60.0

    # Maximum retry attempts
    max_retries: int = 5

    # Base delay for exponential backoff (seconds)
    base_delay: float = 1.0

    # Maximum delay between retries (seconds)
    max_delay: float = 60.0

    # Jitter factor (0.0 to 1.0) to add randomness to delays
    jitter_factor: float = 0.1


@dataclass
class RateLimiter:
    """Token bucket rate limiter with sliding window.

    Tracks request timestamps and enforces rate limits by waiting
    when the limit is exceeded.
    """

    config: RateLimitConfig = field(default_factory=RateLimitConfig)
    _request_times: deque[float] = field(default_factory=deque, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def _cleanup_old_requests(self, now: float) -> None:
        """Remove request timestamps outside the current window."""
        cutoff = now - self.config.window_seconds
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()

    async def acquire(self) -> None:
        """Acquire permission to make a request.

        Blocks if rate limit is exceeded until a slot becomes available.
        """
        async with self._lock:
            now = time.monotonic()
            self._cleanup_old_requests(now)

            if len(self._request_times) >= self.config.max_requests:
                # Calculate wait time until oldest request expires
                oldest = self._request_times[0]
                wait_time = (oldest + self.config.window_seconds) - now

                if wait_time > 0:
                    logger.warning(
                        "rate_limit_wait",
                        wait_seconds=round(wait_time, 2),
                        current_requests=len(self._request_times),
                        max_requests=self.config.max_requests,
                    )
                    await asyncio.sleep(wait_time)
                    now = time.monotonic()
                    self._cleanup_old_requests(now)

            self._request_times.append(now)

    def get_remaining_requests(self) -> int:
        """Get the number of requests remaining in current window."""
        now = time.monotonic()
        self._cleanup_old_requests(now)
        return max(0, self.config.max_requests - len(self._request_times))

    def calculate_backoff_delay(self, attempt: int, retry_after: float | None = None) -> float:
        """Calculate delay for exponential backoff.

        Args:
            attempt: Current retry attempt (0-indexed).
            retry_after: Optional server-specified retry delay.

        Returns:
            Delay in seconds before next retry.
        """
        if retry_after is not None and retry_after > 0:
            # Use server-specified delay with small jitter
            jitter = random.uniform(0, self.config.jitter_factor * retry_after)
            return float(min(retry_after + jitter, self.config.max_delay))

        # Exponential backoff: base_delay * 2^attempt
        delay = self.config.base_delay * (2**attempt)

        # Add jitter
        jitter = random.uniform(0, self.config.jitter_factor * delay)
        delay += jitter

        return float(min(delay, self.config.max_delay))

    def should_retry(self, attempt: int) -> bool:
        """Check if another retry attempt should be made.

        Args:
            attempt: Current retry attempt (0-indexed).

        Returns:
            True if retry should be attempted.
        """
        return attempt < self.config.max_retries


class EndpointRateLimiter:
    """Rate limiter that tracks limits per endpoint.

    Some APIs have different rate limits for different endpoints.
    This class manages multiple rate limiters.
    """

    def __init__(self, default_config: RateLimitConfig | None = None) -> None:
        """Initialize the endpoint rate limiter.

        Args:
            default_config: Default config for new endpoints.
        """
        self._default_config = default_config or RateLimitConfig()
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = asyncio.Lock()

    def configure_endpoint(self, endpoint: str, config: RateLimitConfig) -> None:
        """Configure rate limit for a specific endpoint.

        Args:
            endpoint: Endpoint path or identifier.
            config: Rate limit configuration for this endpoint.
        """
        self._limiters[endpoint] = RateLimiter(config=config)

    async def acquire(self, endpoint: str) -> None:
        """Acquire permission for an endpoint request.

        Args:
            endpoint: Endpoint path or identifier.
        """
        async with self._lock:
            if endpoint not in self._limiters:
                self._limiters[endpoint] = RateLimiter(config=self._default_config)

        await self._limiters[endpoint].acquire()

    def get_limiter(self, endpoint: str) -> RateLimiter:
        """Get the rate limiter for an endpoint.

        Args:
            endpoint: Endpoint path or identifier.

        Returns:
            RateLimiter for the endpoint.
        """
        if endpoint not in self._limiters:
            self._limiters[endpoint] = RateLimiter(config=self._default_config)
        return self._limiters[endpoint]


async def with_retry[T](
    coro_func: Callable[[], Awaitable[T]],
    rate_limiter: RateLimiter,
    *,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Execute a coroutine with retry logic.

    Args:
        coro_func: Async function to execute (will be called on each retry).
        rate_limiter: Rate limiter for backoff configuration.
        retryable_exceptions: Exception types that should trigger a retry.

    Returns:
        Result of the coroutine.

    Raises:
        Exception: The last exception if all retries are exhausted.
    """
    last_exception: Exception | None = None

    for attempt in range(rate_limiter.config.max_retries + 1):
        try:
            return await coro_func()
        except retryable_exceptions as e:
            last_exception = e

            if not rate_limiter.should_retry(attempt):
                logger.error(
                    "retry_exhausted",
                    attempt=attempt,
                    max_retries=rate_limiter.config.max_retries,
                    error=str(e),
                )
                raise

            # Check for retry-after header in rate limit errors
            retry_after: float | None = None
            if hasattr(e, "retry_after"):
                retry_after = e.retry_after

            delay = rate_limiter.calculate_backoff_delay(attempt, retry_after)
            logger.warning(
                "retry_attempt",
                attempt=attempt + 1,
                max_retries=rate_limiter.config.max_retries,
                delay_seconds=round(delay, 2),
                error=str(e),
            )

            await asyncio.sleep(delay)

    # Should not reach here, but satisfy type checker
    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected state in retry logic")
