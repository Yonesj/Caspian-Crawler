import json
import random
from pathlib import Path

import pytest

from core.sources import ratelimit
from core.sources.config import SourcePolicy

FIXTURES = Path(__file__).parent / 'fixtures'


def fixture_text(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


def fixture_json(name):
    return json.loads(fixture_text(name))


def first_fixture(pattern):
    matches = sorted(FIXTURES.glob(pattern))
    assert matches, f'no fixture matched {pattern}'
    return matches[0]


class FakeClock:
    """Virtual monotonic clock that records every sleep instead of taking it."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def time(self) -> float:
        return self.now


class RecordingLimiter:
    """Rate limiter that never waits but records every acquisition."""

    def __init__(self):
        self.calls: list[str] = []

    def acquire(self, source, policy):
        self.calls.append(source)
        return 0.0


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def rng():
    return random.Random(0)


@pytest.fixture(autouse=True)
def clear_limiter_cache():
    ratelimit.clear_rate_limiters()
    yield
    ratelimit.clear_rate_limiters()


def make_policy(**overrides) -> SourcePolicy:
    values = {
        'requests_per_second': 1000.0,
        'burst': 1,
        'timeout_seconds': 5.0,
        'connect_timeout_seconds': 5.0,
        'max_attempts': 3,
        'backoff_base_seconds': 0.75,
        'backoff_factor': 2.0,
        'backoff_max_seconds': 30.0,
        'max_retry_after_seconds': 60.0,
        'max_response_bytes': 1024 * 1024,
        'enabled': True,
    }
    values.update(overrides)
    return SourcePolicy(**values)
