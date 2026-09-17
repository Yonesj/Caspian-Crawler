"""Deliberate, configurable request pacing.

A token bucket per source: ``requests_per_second`` refills the bucket and
``burst`` caps it, so a crawl can never turn into an uncontrolled request loop.
Two implementations share the same behaviour:

* ``InMemoryRateLimiter`` — one bucket per process; fine for development, tests
  and a single worker.
* ``RedisRateLimiter`` — one bucket per *source*, shared by every worker, which
  is what keeps the effective rate honest once Celery runs several processes.

Both block until a token is available and return how long they waited, which
makes the pacing observable in crawl reports.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Protocol

import redis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .config import SourcePolicy

logger = logging.getLogger('north_estate.crawl')

KEY_PREFIX = 'north_estate:ratelimit'


class RateLimiter(Protocol):
    def acquire(self, source: str, policy: SourcePolicy) -> float:
        """Block until one request may be made; return the seconds waited."""


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class InMemoryRateLimiter:
    """Per-process token bucket."""

    def __init__(self, *, sleep=time.sleep, monotonic=time.monotonic):
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._sleep = sleep
        self._monotonic = monotonic

    def acquire(self, source: str, policy: SourcePolicy) -> float:
        waited = 0.0
        while True:
            with self._lock:
                now = self._monotonic()
                bucket = self._buckets.get(source)
                if bucket is None:
                    bucket = _Bucket(tokens=policy.burst, updated_at=now)
                    self._buckets[source] = bucket

                elapsed = max(0.0, now - bucket.updated_at)
                bucket.tokens = min(
                    policy.burst, bucket.tokens + elapsed * policy.requests_per_second
                )
                bucket.updated_at = now

                if bucket.tokens >= 1:
                    bucket.tokens -= 1
                    return waited
                wait_for = (1 - bucket.tokens) / policy.requests_per_second

            self._sleep(wait_for)
            waited += wait_for


class RedisRateLimiter:
    """Token bucket shared by every worker through Redis.

    The bucket is read and written under ``WATCH``/``MULTI`` so concurrent
    workers cannot both spend the same token.  It uses client time, so workers
    are expected to share a clock (they do in the compose setup); a few seconds
    of skew only shifts pacing, it cannot exceed the budget.
    """

    def __init__(self, *, client, sleep=time.sleep, now=time.time, key_prefix=KEY_PREFIX):
        self._client = client
        self._sleep = sleep
        self._now = now
        self._key_prefix = key_prefix

    def acquire(self, source: str, policy: SourcePolicy) -> float:
        waited = 0.0
        while True:
            wait_for = self._try_acquire(source, policy)
            if wait_for <= 0:
                return waited
            self._sleep(wait_for)
            waited += wait_for

    def _try_acquire(self, source: str, policy: SourcePolicy) -> float:
        key = f'{self._key_prefix}:{source}'
        ttl = max(60, int(2 * policy.burst / policy.requests_per_second))
        while True:
            try:
                with self._client.pipeline() as pipe:
                    pipe.watch(key)
                    values = pipe.hmget(key, 'tokens', 'ts')
                    now = self._now()
                    tokens = float(values[0]) if values[0] is not None else policy.burst
                    updated_at = float(values[1]) if values[1] is not None else now
                    tokens = min(
                        policy.burst,
                        tokens
                        + max(0.0, now - updated_at) * policy.requests_per_second,
                    )
                    if tokens >= 1:
                        tokens -= 1
                        wait_for = 0.0
                    else:
                        wait_for = (1 - tokens) / policy.requests_per_second

                    pipe.multi()
                    pipe.hset(key, mapping={'tokens': tokens, 'ts': now})
                    pipe.expire(key, ttl)
                    pipe.execute()
                    return wait_for
            except redis.WatchError:
                # Another worker spent a token first: recompute and retry.
                continue


_LIMITERS: dict[str, RateLimiter] = {}


def clear_rate_limiters() -> None:
    """Forget cached limiters (used by tests that swap the backend)."""
    _LIMITERS.clear()


def get_rate_limiter(backend: str | None = None) -> RateLimiter:
    """Return the process-wide limiter for the configured backend."""
    backend = backend or getattr(settings, 'CRAWL_RATE_LIMIT_BACKEND', 'memory')
    if backend in _LIMITERS:
        return _LIMITERS[backend]

    if backend == 'memory':
        limiter: RateLimiter = InMemoryRateLimiter()
    elif backend == 'redis':
        url = getattr(settings, 'REDIS_URL', 'redis://127.0.0.1:6379/0')
        limiter = RedisRateLimiter(client=redis.Redis.from_url(url))
    else:
        raise ImproperlyConfigured(
            f'CRAWL_RATE_LIMIT_BACKEND must be "memory" or "redis", got {backend!r}'
        )

    _LIMITERS[backend] = limiter
    logger.debug('rate limiter backend: %s', backend)
    return limiter
