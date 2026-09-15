"""Bounded exponential backoff for transient provider failures.

This only retries errors the provider marks as transient (rate limiting,
temporary unavailability), with a hard retry cap. It does not rotate
credentials, IPs or anything else — it simply waits and tries again.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from app.providers.base import ProviderError

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 2.0
    max_delay: float = 60.0

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        delay = min(self.max_delay, self.base_delay * (2**attempt))
        if retry_after is not None:
            delay = max(delay, min(retry_after, self.max_delay))
        # Small jitter so concurrent jobs do not retry in lock-step.
        return delay + random.uniform(0, delay * 0.1)


def call_with_retry(
    fn: Callable[[], T],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], None] = time.sleep,
    operation: str = "provider call",
) -> T:
    attempt = 0
    while True:
        try:
            return fn()
        except ProviderError as exc:
            if not exc.retryable or attempt >= policy.max_retries:
                raise
            delay = policy.delay_for(attempt, exc.retry_after)
            logger.warning(
                "Transient provider error; retrying",
                extra={
                    "operation": operation,
                    "error_code": str(exc.code),
                    "attempt": attempt + 1,
                    "max_retries": policy.max_retries,
                    "delay_seconds": round(delay, 2),
                },
            )
            sleep(delay)
            attempt += 1
