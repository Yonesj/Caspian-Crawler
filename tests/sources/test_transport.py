import httpx
import pytest
import respx
from django.test import override_settings

from core.sources.errors import (
    PermanentHTTPError,
    ResponseTooLarge,
    SourceDisabled,
    TransientHTTPError,
    TransportError,
)
from core.sources.transport import FetchRequest, HttpxFetcher, parse_retry_after
from tests.sources.conftest import RecordingLimiter, make_policy

URL = 'https://example.test/list'
REQUEST = FetchRequest(method='GET', url=URL, source='divar')


def build_fetcher(clock, rng, *, limiter=None, jitter_ratio=0.0, **policy_overrides):
    return HttpxFetcher(
        client=httpx.Client(),
        limiter=limiter if limiter is not None else RecordingLimiter(),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        rng=rng,
        jitter_ratio=jitter_ratio,
        user_agent='NorthEstate/test',
    )


def policy_settings(**overrides):
    return override_settings(CRAWL_POLICIES={'divar': make_policy(**overrides)})


@respx.mock
def test_retries_transient_status_then_succeeds(clock, rng):
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, text='ok')]
    )
    fetcher = build_fetcher(clock, rng)

    with policy_settings():
        response = fetcher.fetch(REQUEST)

    assert response.status_code == 200
    assert response.attempts == 2
    assert route.call_count == 2
    assert clock.sleeps == [0.75]


@respx.mock
def test_gives_up_after_max_attempts(clock, rng):
    route = respx.get(URL).mock(return_value=httpx.Response(503))
    fetcher = build_fetcher(clock, rng)

    with policy_settings(max_attempts=3), pytest.raises(TransientHTTPError):
        fetcher.fetch(REQUEST)

    assert route.call_count == 3
    assert clock.sleeps == [0.75, 1.5]


@respx.mock
@pytest.mark.parametrize('status', [400, 401, 403, 404, 410])
def test_permanent_statuses_are_never_retried(clock, rng, status):
    route = respx.get(URL).mock(return_value=httpx.Response(status))
    fetcher = build_fetcher(clock, rng)

    with policy_settings(), pytest.raises(PermanentHTTPError) as excinfo:
        fetcher.fetch(REQUEST)

    assert excinfo.value.status_code == status
    assert route.call_count == 1
    assert clock.sleeps == []


@respx.mock
def test_retries_408_and_425(clock, rng):
    respx.get(URL).mock(
        side_effect=[httpx.Response(408), httpx.Response(425), httpx.Response(200)]
    )
    fetcher = build_fetcher(clock, rng)

    with policy_settings(backoff_base_seconds=1.0):
        response = fetcher.fetch(REQUEST)

    assert response.status_code == 200
    assert clock.sleeps == [1.0, 2.0]


@respx.mock
def test_retry_after_seconds_is_honoured_on_429(clock, rng):
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={'Retry-After': '5'}),
            httpx.Response(200, text='ok'),
        ]
    )
    fetcher = build_fetcher(clock, rng)

    with policy_settings(backoff_base_seconds=0.75):
        fetcher.fetch(REQUEST)

    assert clock.sleeps == [5.0]


@respx.mock
def test_retry_after_beyond_the_cap_fails_fast(clock, rng):
    route = respx.get(URL).mock(
        return_value=httpx.Response(503, headers={'Retry-After': '9999'})
    )
    fetcher = build_fetcher(clock, rng)

    with policy_settings(max_retry_after_seconds=60), pytest.raises(TransientHTTPError):
        fetcher.fetch(REQUEST)

    assert route.call_count == 1
    assert clock.sleeps == []


@respx.mock
def test_connection_errors_are_retried_with_growing_backoff(clock, rng):
    respx.get(URL).mock(
        side_effect=[
            httpx.ConnectError('boom'),
            httpx.ReadTimeout('slow'),
            httpx.Response(200, text='ok'),
        ]
    )
    fetcher = build_fetcher(clock, rng)

    with policy_settings():
        response = fetcher.fetch(REQUEST)

    assert response.attempts == 3
    assert clock.sleeps == [0.75, 1.5]


@respx.mock
def test_connection_errors_exhaust_the_budget(clock, rng):
    route = respx.get(URL).mock(side_effect=httpx.ConnectError('down'))
    fetcher = build_fetcher(clock, rng)

    with policy_settings(max_attempts=2), pytest.raises(TransportError):
        fetcher.fetch(REQUEST)

    assert route.call_count == 2


@respx.mock
def test_oversized_response_is_not_retried(clock, rng):
    route = respx.get(URL).mock(return_value=httpx.Response(200, text='x' * 200))
    fetcher = build_fetcher(clock, rng)

    with policy_settings(max_response_bytes=100), pytest.raises(ResponseTooLarge) as excinfo:
        fetcher.fetch(REQUEST)

    assert excinfo.value.size == 200
    assert route.call_count == 1


@respx.mock
def test_backoff_is_jittered_within_half_the_delay(clock, rng):
    respx.get(URL).mock(side_effect=[httpx.Response(500), httpx.Response(200)])
    fetcher = build_fetcher(clock, rng, jitter_ratio=0.5)

    with policy_settings(backoff_base_seconds=4.0):
        fetcher.fetch(REQUEST)

    assert 2.0 <= clock.sleeps[0] <= 4.0


@respx.mock
def test_limiter_is_consulted_for_every_attempt(clock, rng):
    respx.get(URL).mock(side_effect=[httpx.Response(500), httpx.Response(200)])
    limiter = RecordingLimiter()
    fetcher = build_fetcher(clock, rng, limiter=limiter)

    with policy_settings():
        fetcher.fetch(REQUEST)

    assert limiter.calls == ['divar', 'divar']


@respx.mock
def test_disabled_source_never_requests(clock, rng):
    route = respx.get(URL).mock(return_value=httpx.Response(200))
    fetcher = build_fetcher(clock, rng)

    with policy_settings(enabled=False), pytest.raises(SourceDisabled):
        fetcher.fetch(REQUEST)

    assert route.call_count == 0


@respx.mock
def test_user_agent_and_custom_headers_are_sent(clock, rng):
    route = respx.get(URL).mock(return_value=httpx.Response(200, text='ok'))
    fetcher = build_fetcher(clock, rng)
    request = FetchRequest(
        method='GET', url=URL, source='divar', headers={'X-Test': 'yes'}
    )

    with policy_settings():
        fetcher.fetch(request)

    sent = route.calls[0].request
    assert sent.headers['user-agent'] == 'NorthEstate/test'
    assert sent.headers['x-test'] == 'yes'


@respx.mock
def test_redirects_are_followed(clock, rng):
    respx.get(URL).mock(return_value=httpx.Response(301, headers={'Location': '/final'}))
    respx.get('https://example.test/final').mock(
        return_value=httpx.Response(200, text='arrived')
    )
    fetcher = build_fetcher(clock, rng)

    with policy_settings():
        response = fetcher.fetch(REQUEST)

    assert response.text == 'arrived'
    assert response.url == 'https://example.test/final'


@pytest.mark.parametrize(
    'header,expected',
    [
        (None, None),
        ('', None),
        ('0', 0.0),
        ('12', 12.0),
        (' 7 ', 7.0),
        ('Wed, 21 Oct 2099 07:28:00 GMT', None),  # far future: only the format matters
        ('not-a-date', None),
    ],
)
def test_parse_retry_after_delta_seconds(header, expected):
    result = parse_retry_after(header)
    if expected is None and header and header.startswith('Wed'):
        assert result is not None and result > 0
    else:
        assert result == expected


def test_parse_retry_after_http_date_is_relative_to_now():
    result = parse_retry_after('Wed, 21 Oct 2015 07:28:00 GMT', now=1445412400.0)
    assert result == 80.0
