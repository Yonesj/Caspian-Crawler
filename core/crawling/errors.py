"""Failures raised by the crawl orchestration layer."""

from core.sources.errors import SourceError


class ScopeResolutionError(SourceError):
    """The saved scope cannot be expressed as a source crawl scope.

    Raised before any request is made, so an operator learns that a place has no
    ``SourceLocation`` mapping (or that a source is disabled) immediately rather
    than from a job that quietly crawled nothing.
    """
