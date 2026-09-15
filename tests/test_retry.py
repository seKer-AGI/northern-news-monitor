import pytest

from app.providers.base import ProviderError, ProviderErrorCode
from app.providers.retry import RetryPolicy, call_with_retry


def test_exponential_backoff_is_capped():
    policy = RetryPolicy(max_retries=5, base_delay=2, max_delay=10)
    delays = [policy.delay_for(i) for i in range(5)]
    assert 2 <= delays[0] <= 2.2
    assert 4 <= delays[1] <= 4.4
    assert all(d <= 11 for d in delays)


def test_retry_after_hint_is_respected_within_cap():
    policy = RetryPolicy(max_retries=1, base_delay=1, max_delay=30)
    assert policy.delay_for(0, retry_after=20) >= 20
    assert policy.delay_for(0, retry_after=500) <= 33


def test_non_retryable_errors_raise_immediately():
    sleeps = []

    def fn():
        raise ProviderError(ProviderErrorCode.PERMISSION_DENIED, "no")

    with pytest.raises(ProviderError):
        call_with_retry(fn, RetryPolicy(max_retries=3), sleep=sleeps.append)
    assert sleeps == []


def test_retryable_errors_eventually_succeed():
    attempts = iter([ProviderError(ProviderErrorCode.RATE_LIMITED, "slow down"), None])
    sleeps = []

    def fn():
        err = next(attempts)
        if err:
            raise err
        return "ok"

    assert (
        call_with_retry(fn, RetryPolicy(max_retries=3, base_delay=0), sleep=sleeps.append) == "ok"
    )
    assert len(sleeps) == 1
