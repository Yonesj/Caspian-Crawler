"""Typed failures for the source layer.

The distinction that matters to callers is *retryable vs permanent*: a crawl
job must record a source as failing rather than retry a 404 forever, and must
back off instead of hammering a 429.
"""


class SourceError(Exception):
    """Base class for every failure raised by the source layer."""


class SourceDisabled(SourceError):
    """The policy for this source has crawling switched off."""


class UnknownSourceError(SourceError):
    """No adapter or policy is registered for the requested source."""


class TransportError(SourceError):
    """Network-level failure that survived the retry budget."""


class TransientHTTPError(TransportError):
    """A retryable HTTP status (408/429/5xx) that exhausted the retry budget."""


class PermanentHTTPError(SourceError):
    """A non-retryable HTTP status (401/403/404 and friends)."""

    def __init__(self, message, *, status_code=None, url=None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class ResponseTooLarge(SourceError):
    """The response body exceeded the policy's byte cap."""

    def __init__(self, message, *, limit=None, size=None):
        super().__init__(message)
        self.limit = limit
        self.size = size


class ParseError(SourceError):
    """A payload no longer matches the shape the source used to return."""
