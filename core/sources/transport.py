"""Resilient HTTP transport shared by every source adapter.

Fault tolerance lives here rather than in adapters so it is written once and
tested once: a defined timeout, bounded retries, exponential backoff with
jitter, explicit ``429``/``Retry-After`` handling, a response-size guard, and a
hard rule that permanent failures (401/403/404...) are never retried.

Time and randomness are injectable so tests exercise backoff without sleeping.
"""

import logging
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from django.conf import settings

from .config import SourcePolicy, policy_for
from .errors import (
    PermanentHTTPError,
    ResponseTooLarge,
    SourceDisabled,
    SourceError,
    TransientHTTPError,
    TransportError,
)
from .ratelimit import get_rate_limiter

logger = logging.getLogger('north_estate.crawl')

# 408/425 are retryable by definition; 429 is handled explicitly (see Retry-After)
# and every 5xx is treated as transient.
RETRYABLE_STATUS = frozenset({408, 425, 429})
DEFAULT_USER_AGENT = 'NorthEstate/0.1 (research crawler)'


@dataclass(frozen=True)
class FetchRequest:
    method: str
    url: str
    source: str
    params: Mapping[str, Any] | None = None
    json_body: Mapping[str, Any] | None = None
    headers: Mapping[str, str] | None = field(default=None)


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status_code: int
    text: str
    headers: dict[str, str]
    attempts: int


def parse_retry_after(value: str | None, *, now: float | None = None) -> float | None:
    """Parse a ``Retry-After`` header into seconds.

    Accepts both forms the RFC allows: a delta in seconds and an HTTP date.
    Returns ``None`` when the header is absent or unparseable.
    """
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None

    reference = now if now is not None else time.time()
    try:
        return max(0.0, when.timestamp() - reference)
    except (OverflowError, OSError, ValueError):
        return None


class HttpxFetcher:
    """Fetcher that applies a source policy to every request."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        limiter=None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
        jitter_ratio: float = 0.5,
        user_agent: str | None = None,
    ):
        self._client = client or httpx.Client(follow_redirects=True)
        self._limiter = limiter
        self._sleep = sleep
        self._monotonic = monotonic
        self._rng = rng or random.Random()
        self._jitter_ratio = min(max(jitter_ratio, 0.0), 1.0)
        self._user_agent = user_agent or getattr(
            settings, 'CRAWL_USER_AGENT', DEFAULT_USER_AGENT
        )

    # -- lifecycle ------------------------------------------------------------
    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    # -- fetching -------------------------------------------------------------
    def fetch(self, request: FetchRequest) -> FetchResponse:
        policy = policy_for(request.source)
        if not policy.enabled:
            raise SourceDisabled(f'Crawling is disabled for source {request.source!r}')

        headers = {'User-Agent': self._user_agent, 'Accept-Language': 'fa-IR,fa;q=0.9'}
        headers.update(request.headers or {})
        timeout = httpx.Timeout(
            policy.timeout_seconds, connect=policy.connect_timeout_seconds
        )

        last_error: SourceError | None = None
        for attempt in range(1, policy.max_attempts + 1):
            self._wait_for_slot(request.source, policy)
            started = self._monotonic()
            delay = None
            try:
                response = self._client.request(
                    request.method,
                    request.url,
                    params=request.params,
                    json=request.json_body,
                    headers=headers,
                    timeout=timeout,
                    follow_redirects=True,
                )
            except httpx.InvalidURL as exc:
                raise SourceError(f'invalid URL {request.url!r}: {exc}') from exc
            except httpx.HTTPError as exc:
                last_error = TransportError(
                    f'{request.source} {request.method} {request.url} failed: {exc!r}'
                )
                if attempt >= policy.max_attempts:
                    logger.warning(
                        'giving up on %s after %d attempts: %r',
                        request.url, attempt, exc,
                    )
                    raise last_error from exc
                delay = self._backoff_delay(policy, attempt)
            else:
                duration = self._monotonic() - started
                status = response.status_code
                if status in RETRYABLE_STATUS or status >= 500:
                    retry_after = parse_retry_after(response.headers.get('Retry-After'))
                    if attempt >= policy.max_attempts:
                        raise TransientHTTPError(
                            f'{request.source} {request.url} returned {status} '
                            f'after {attempt} attempts'
                        )
                    delay = (
                        retry_after
                        if retry_after is not None
                        else self._backoff_delay(policy, attempt)
                    )
                    if delay > policy.max_retry_after_seconds:
                        raise TransientHTTPError(
                            f'{request.source} {request.url} asked to wait {delay:.0f}s '
                            f'(limit {policy.max_retry_after_seconds:.0f}s)'
                        )
                    logger.warning(
                        'retrying %s in %.2fs (status %s, attempt %d)',
                        request.url, delay, status, attempt,
                    )
                elif 400 <= status < 500:
                    raise PermanentHTTPError(
                        f'{request.source} {request.url} returned {status}',
                        status_code=status,
                        url=request.url,
                    )
                else:
                    body = response.content
                    if len(body) > policy.max_response_bytes:
                        raise ResponseTooLarge(
                            f'{request.source} {request.url} returned {len(body)} bytes '
                            f'(limit {policy.max_response_bytes})',
                            limit=policy.max_response_bytes,
                            size=len(body),
                        )
                    try:
                        text = response.text
                    except httpx.DecodingError as exc:
                        raise SourceError(
                            f'could not decode {request.url}: {exc}'
                        ) from exc
                    logger.debug(
                        'fetched %s in %.2fs (status %s, attempt %d)',
                        request.url, duration, status, attempt,
                    )
                    return FetchResponse(
                        url=str(response.url),
                        status_code=status,
                        text=text,
                        headers=dict(response.headers),
                        attempts=attempt,
                    )

            if delay is not None:
                self._sleep(delay)

        raise last_error or TransportError(
            f'{request.source} {request.url} exhausted its retry budget'
        )

    # -- helpers --------------------------------------------------------------
    def _wait_for_slot(self, source: str, policy: SourcePolicy):
        limiter = self._limiter if self._limiter is not None else get_rate_limiter()
        waited = limiter.acquire(source, policy)
        if waited > 0:
            logger.debug('rate limit: waited %.2fs before requesting %s', waited, source)

    def _backoff_delay(self, policy: SourcePolicy, attempt: int) -> float:
        raw = min(
            policy.backoff_max_seconds,
            policy.backoff_base_seconds * policy.backoff_factor ** (attempt - 1),
        )
        if self._jitter_ratio <= 0:
            return raw
        return raw * (1 - self._rng.uniform(0.0, self._jitter_ratio))


_FETCHER: HttpxFetcher | None = None


def get_fetcher() -> HttpxFetcher:
    """Process-wide fetcher (keeps one connection pool per worker)."""
    global _FETCHER
    if _FETCHER is None:
        _FETCHER = HttpxFetcher()
    return _FETCHER
