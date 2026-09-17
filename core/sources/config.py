"""Per-source crawl policies.

Every knob is a value an operator may need to change without touching code, so
policies live in Django settings (``CRAWL_POLICIES``) and are filled from the
environment in ``config/settings/base.py`` using ``CRAWL_<SOURCE>_<FIELD>``.
"""

from dataclasses import dataclass, fields, replace

from django.conf import settings

from .errors import UnknownSourceError


@dataclass(frozen=True)
class SourcePolicy:
    """How politely and how patiently we may talk to one source."""

    requests_per_second: float
    burst: int
    timeout_seconds: float
    connect_timeout_seconds: float
    max_attempts: int
    backoff_base_seconds: float
    backoff_factor: float
    backoff_max_seconds: float
    max_retry_after_seconds: float
    max_response_bytes: int
    enabled: bool = True

    def __post_init__(self):
        if self.requests_per_second <= 0:
            raise ValueError('requests_per_second must be > 0')
        if self.burst < 1:
            raise ValueError('burst must be >= 1')
        if self.timeout_seconds <= 0 or self.connect_timeout_seconds <= 0:
            raise ValueError('timeouts must be > 0')
        if self.max_attempts < 1:
            raise ValueError('max_attempts must be >= 1')
        if self.backoff_base_seconds <= 0 or self.backoff_max_seconds <= 0:
            raise ValueError('backoff values must be > 0')
        if self.backoff_factor < 1:
            raise ValueError('backoff_factor must be >= 1')
        if self.max_response_bytes < 1:
            raise ValueError('max_response_bytes must be >= 1')


# Conservative defaults: one request every two seconds to Divar, one every
# three seconds to Sheypoor, and four attempts at most.
DEFAULT_POLICIES = {
    'divar': SourcePolicy(
        requests_per_second=0.5,
        burst=1,
        timeout_seconds=20.0,
        connect_timeout_seconds=5.0,
        max_attempts=4,
        backoff_base_seconds=0.75,
        backoff_factor=2.0,
        backoff_max_seconds=30.0,
        max_retry_after_seconds=60.0,
        max_response_bytes=8 * 1024 * 1024,
    ),
    'sheypoor': SourcePolicy(
        requests_per_second=1 / 3,
        burst=1,
        timeout_seconds=30.0,
        connect_timeout_seconds=5.0,
        max_attempts=4,
        backoff_base_seconds=1.0,
        backoff_factor=2.0,
        backoff_max_seconds=60.0,
        max_retry_after_seconds=120.0,
        max_response_bytes=8 * 1024 * 1024,
    ),
}

# field name -> (env suffix, cast)
_ENV_FIELDS = {
    'requests_per_second': ('REQUESTS_PER_SECOND', float),
    'burst': ('BURST', int),
    'timeout_seconds': ('TIMEOUT_SECONDS', float),
    'connect_timeout_seconds': ('CONNECT_TIMEOUT_SECONDS', float),
    'max_attempts': ('MAX_ATTEMPTS', int),
    'backoff_base_seconds': ('BACKOFF_BASE_SECONDS', float),
    'backoff_factor': ('BACKOFF_FACTOR', float),
    'backoff_max_seconds': ('BACKOFF_MAX_SECONDS', float),
    'max_retry_after_seconds': ('MAX_RETRY_AFTER_SECONDS', float),
    'max_response_bytes': ('MAX_RESPONSE_BYTES', int),
    'enabled': ('ENABLED', None),
}


def build_policies(env_str, env_bool, sources=None):
    """Build the ``CRAWL_POLICIES`` mapping from the environment.

    ``env_str``/``env_bool`` are Django settings' helpers, passed in so this
    module stays independent of any particular settings module.
    """
    sources = sources or tuple(DEFAULT_POLICIES)
    policies = {}
    for source in sources:
        defaults = DEFAULT_POLICIES[source]
        overrides = {}
        for field in fields(SourcePolicy):
            suffix, cast = _ENV_FIELDS[field.name]
            name = f'CRAWL_{source.upper()}_{suffix}'
            if cast is None:
                value = env_bool(name, getattr(defaults, field.name))
            else:
                raw = env_str(name)
                if raw in (None, ''):
                    continue
                try:
                    value = cast(raw)
                except ValueError as exc:
                    raise ValueError(f'{name}={raw!r} is not a valid value') from exc
            overrides[field.name] = value
        policies[source] = replace(defaults, **overrides)
    return policies


def policy_for(source: str) -> SourcePolicy:
    """Resolve the effective policy for a source."""
    source = str(source)
    configured = (getattr(settings, 'CRAWL_POLICIES', None) or {}).get(source)
    if configured is not None:
        return configured
    try:
        return DEFAULT_POLICIES[source]
    except KeyError:
        raise UnknownSourceError(f'No crawl policy configured for source {source!r}')
