"""Retry logic with exponential backoff and jitter."""

import logging
import random
import time

logger = logging.getLogger(__name__)


def exponential_backoff(
    attempt: int,
    base: float = 2.0,
    max_delay: float = 120.0,
    jitter: bool = True,
) -> float:
    """Calculate delay for exponential backoff.

    Args:
        attempt: 0-indexed attempt number
        base: Base delay in seconds
        max_delay: Maximum delay cap
        jitter: Add random jitter to prevent thundering herd
    """
    delay = min(base * (2 ** attempt), max_delay)
    if jitter:
        delay = delay * (0.5 + random.random() * 0.5)
    return delay


def retry_with_backoff(
    fn,
    max_attempts: int = 3,
    base: float = 2.0,
    max_delay: float = 120.0,
    retryable_exceptions: tuple = (Exception,),
    on_retry=None,
):
    """Execute fn with retry and exponential backoff.

    Args:
        fn: Callable to execute
        max_attempts: Maximum number of attempts
        base: Base delay for backoff
        max_delay: Maximum delay cap
        retryable_exceptions: Tuple of exception types that trigger retry
        on_retry: Optional callback(attempt, exception, delay) called before each retry sleep
    """
    last_error = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except retryable_exceptions as e:
            last_error = e
            if attempt < max_attempts - 1:
                delay = exponential_backoff(attempt, base, max_delay)
                if on_retry:
                    on_retry(attempt, e, delay)
                else:
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_attempts} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                time.sleep(delay)
            else:
                raise
    raise last_error  # Should not reach here
