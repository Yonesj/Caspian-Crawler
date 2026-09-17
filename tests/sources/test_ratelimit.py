import fakeredis
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from core.sources.ratelimit import (
    InMemoryRateLimiter,
    RedisRateLimiter,
    get_rate_limiter,
)
from tests.sources.conftest import make_policy


def test_in_memory_bucket_allows_burst_then_paces(clock):
    limiter = InMemoryRateLimiter(sleep=clock.sleep, monotonic=clock.monotonic)
    policy = make_policy(requests_per_second=1.0, burst=2)

    assert limiter.acquire('divar', policy) == 0.0
    assert limiter.acquire('divar', policy) == 0.0
    waited = limiter.acquire('divar', policy)

    assert waited == pytest.approx(1.0)
    assert clock.sleeps == [pytest.approx(1.0)]


def test_in_memory_buckets_are_per_source(clock):
    limiter = InMemoryRateLimiter(sleep=clock.sleep, monotonic=clock.monotonic)
    policy = make_policy(requests_per_second=1.0, burst=1)

    limiter.acquire('divar', policy)
    assert limiter.acquire('sheypoor', policy) == 0.0
    assert clock.sleeps == []


def test_in_memory_refills_over_time(clock):
    limiter = InMemoryRateLimiter(sleep=clock.sleep, monotonic=clock.monotonic)
    policy = make_policy(requests_per_second=0.5, burst=1)

    limiter.acquire('divar', policy)
    clock.now += 2.0  # exactly one token at 0.5 rps
    assert limiter.acquire('divar', policy) == 0.0


def test_redis_bucket_is_shared_between_workers(clock):
    client = fakeredis.FakeStrictRedis()
    policy = make_policy(requests_per_second=1.0, burst=1)
    worker_a = RedisRateLimiter(client=client, sleep=clock.sleep, now=clock.time)
    worker_b = RedisRateLimiter(client=client, sleep=clock.sleep, now=clock.time)

    assert worker_a.acquire('divar', policy) == 0.0
    waited = worker_b.acquire('divar', policy)

    assert waited == pytest.approx(1.0)
    assert clock.sleeps == [pytest.approx(1.0)]
    assert client.hget('north_estate:ratelimit:divar', 'tokens') is not None
    assert client.ttl('north_estate:ratelimit:divar') > 0


def test_redis_bucket_refills_and_honours_burst(clock):
    client = fakeredis.FakeStrictRedis()
    policy = make_policy(requests_per_second=2.0, burst=2)
    limiter = RedisRateLimiter(client=client, sleep=clock.sleep, now=clock.time)

    assert limiter.acquire('divar', policy) == 0.0
    assert limiter.acquire('divar', policy) == 0.0

    waited = limiter.acquire('divar', policy)
    assert waited == pytest.approx(0.5)


@override_settings(CRAWL_RATE_LIMIT_BACKEND='memory')
def test_factory_returns_a_process_wide_memory_limiter():
    first = get_rate_limiter()
    second = get_rate_limiter()

    assert isinstance(first, InMemoryRateLimiter)
    assert first is second


@override_settings(
    CRAWL_RATE_LIMIT_BACKEND='redis', REDIS_URL='redis://localhost:6379/9'
)
def test_factory_builds_a_redis_limiter_without_connecting():
    limiter = get_rate_limiter()

    assert isinstance(limiter, RedisRateLimiter)
    assert get_rate_limiter() is limiter


@override_settings(CRAWL_RATE_LIMIT_BACKEND='carrier-pigeon')
def test_unknown_backend_is_a_configuration_error():
    with pytest.raises(ImproperlyConfigured):
        get_rate_limiter()
