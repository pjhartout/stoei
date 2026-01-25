"""Resilience decorators for SLURM command execution.

Provides decorators for adding timeout and retry functionality to functions.
"""

import functools
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import ParamSpec, TypeVar

from stoei.logger import get_logger

logger = get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 1.5
DEFAULT_INITIAL_DELAY = 0.5


def with_timeout(seconds: float) -> Callable[[Callable[P, T]], Callable[P, T | None]]:
    """Decorator that enforces a timeout on function execution.

    If the function takes longer than the specified timeout, it returns None.

    Args:
        seconds: Maximum execution time in seconds.

    Returns:
        Decorator function.

    Example:
        @with_timeout(5.0)
        def slow_function():
            # This will return None if it takes more than 5 seconds
            ...
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T | None]:
        func_name = getattr(func, "__name__", repr(func))

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T | None:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, *args, **kwargs)
                try:
                    return future.result(timeout=seconds)
                except FuturesTimeoutError:
                    logger.warning(f"Timeout after {seconds}s in {func_name}")
                    return None
                except Exception:
                    logger.exception(f"Error in {func_name}")
                    return None

        return wrapper

    return decorator


def with_retry(
    max_attempts: int = DEFAULT_MAX_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator that adds exponential backoff retry to a function.

    Args:
        max_attempts: Maximum number of attempts (including the first one).
        backoff_factor: Factor to multiply delay by after each retry.
        initial_delay: Initial delay in seconds before first retry.
        retryable_exceptions: Tuple of exception types that should trigger a retry.

    Returns:
        Decorator function.

    Example:
        @with_retry(max_attempts=3, backoff_factor=2.0)
        def flaky_function():
            # This will retry up to 3 times with exponential backoff
            ...
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        func_name = getattr(func, "__name__", repr(func))

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            delay = initial_delay
            last_exception: Exception | None = None

            for attempt in range(max_attempts):
                try:
                    result = func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exception = exc
                    if attempt < max_attempts - 1:
                        logger.debug(
                            f"{func_name} failed (attempt {attempt + 1}/{max_attempts}), "
                            f"retrying in {delay:.1f}s: {exc}"
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.warning(f"{func_name} failed after {max_attempts} attempts: {exc}")
                else:
                    if attempt > 0:
                        logger.debug(f"{func_name} succeeded on attempt {attempt + 1}")
                    return result

            # If we get here, all attempts failed
            if last_exception is not None:
                raise last_exception
            # This should never happen, but satisfy type checker
            msg = f"{func_name} failed with no exception recorded"
            raise RuntimeError(msg)  # pragma: no cover

        return wrapper

    return decorator


def resilient(
    timeout: float,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
) -> Callable[[Callable[P, T]], Callable[P, T | None]]:
    """Decorator that combines timeout and retry functionality.

    Each retry attempt has its own timeout. If a single attempt times out,
    it counts as a failure and triggers a retry (if retries remain).

    Args:
        timeout: Timeout in seconds for each attempt.
        max_retries: Maximum number of retry attempts (in addition to the first).
        backoff_factor: Factor to multiply delay by after each retry.
        initial_delay: Initial delay in seconds before first retry.

    Returns:
        Decorator function.

    Example:
        @resilient(timeout=5.0, max_retries=3)
        def critical_function():
            # This will timeout after 5s per attempt, retry up to 3 additional times
            ...
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T | None]:
        func_name = getattr(func, "__name__", repr(func))

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T | None:
            delay = initial_delay
            total_attempts = max_retries + 1

            for attempt in range(total_attempts):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(func, *args, **kwargs)
                    try:
                        result = future.result(timeout=timeout)
                    except FuturesTimeoutError:
                        logger.debug(f"{func_name} timed out (attempt {attempt + 1}/{total_attempts})")
                    except Exception as exc:
                        logger.debug(f"{func_name} failed (attempt {attempt + 1}/{total_attempts}): {exc}")
                    else:
                        if attempt > 0:
                            logger.debug(f"{func_name} succeeded on attempt {attempt + 1}")
                        return result

                # Wait before retry (except on last attempt)
                if attempt < total_attempts - 1:
                    logger.debug(f"{func_name} retrying in {delay:.1f}s")
                    time.sleep(delay)
                    delay *= backoff_factor

            logger.warning(f"{func_name} failed after {total_attempts} attempts")
            return None

        return wrapper

    return decorator
