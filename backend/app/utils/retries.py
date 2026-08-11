"""
Phase 12 — Bounded Exponential Backoff Retry Utility.

Provides robust retry mechanics for external API calls (GitHub, Gemini, Postgres, Redis).
Differs between transient retryable errors (429, 500, 502, 503, 504, timeout)
and non-retryable errors (400, 401, 403, 422, schema validation errors).
"""

import time
from typing import Callable, TypeVar, Any
from app.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# Status codes considered transient/retryable
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Status codes that must NEVER be retried
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 422}


def is_transient_error(exc: Exception) -> bool:
    """
    Determine if an exception represents a transient failure eligible for retry.
    """
    err_msg = str(exc)
    err_name = type(exc).__name__

    # Check for HTTP status code attributes or strings
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status_code and isinstance(status_code, int):
        if status_code in NON_RETRYABLE_STATUS_CODES:
            return False
        if status_code in RETRYABLE_STATUS_CODES:
            return True

    # String checks for rate limits / timeouts / connection errors
    if any(code in err_msg for code in ["429", "500", "502", "503", "504", "RESOURCE_EXHAUSTED"]):
        return True

    if any(term in err_name.lower() or term in err_msg.lower() for term in ["timeout", "connectionerror", "connecttimeout", "readtimeout"]):
        return True

    return False


def execute_with_retry(
    func: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 2.0,
    operation_name: str = "operation",
) -> T:
    """
    Execute a function with exponential backoff retries for transient errors.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except Exception as exc:
            if attempt == max_retries or not is_transient_error(exc):
                logger.error(
                    "[%s] Permanent failure or max retries reached (%d/%d): %s",
                    operation_name,
                    attempt,
                    max_retries,
                    exc,
                )
                raise exc

            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "[%s] Transient error (%s). Retrying in %.1fs (attempt %d/%d)...",
                operation_name,
                exc,
                delay,
                attempt,
                max_retries,
            )
            time.sleep(delay)

    raise RuntimeError(f"[{operation_name}] Retries exhausted")
