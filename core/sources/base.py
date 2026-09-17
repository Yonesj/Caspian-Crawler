"""Adapter contract shared by every crawl source.

Fetching, parsing, normalization, persistence and dedup are separate concerns;
this module owns only the seam between "the crawler" and "a source".  Parsers
are pure functions of a payload so they can be tested from saved fixtures, and
adapters never touch the database.
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from .dto import CrawlScope, ListingDetail, ListingStub, ListPage
from .errors import ParseError
from .transport import FetchResponse, HttpxFetcher, get_fetcher


class SourceAdapter(ABC):
    """Turns a crawl scope into source-shaped DTOs.

    ``fetch_detail`` takes the source id because that is the stable identity,
    but sources that only accept slugged URLs (Sheypoor) also need the URL the
    listing was discovered at; those adapters raise if ``url`` is missing
    rather than guessing.
    """

    source: str

    def __init__(self, fetcher: HttpxFetcher | None = None):
        self._fetcher = fetcher

    @property
    def fetcher(self) -> HttpxFetcher:
        return self._fetcher if self._fetcher is not None else get_fetcher()

    @abstractmethod
    def iter_list_pages(self, scope: CrawlScope) -> Iterator[ListPage]:
        """Yield successive pages of listings for a scope."""

    @abstractmethod
    def fetch_detail(self, source_id: str, *, url: str | None = None) -> ListingDetail:
        """Fetch and parse one listing's detail page."""

    def iter_listings(self, scope: CrawlScope) -> Iterator[ListingStub]:
        for page in self.iter_list_pages(scope):
            yield from page.items


def load_json(response: FetchResponse, source: str) -> Any:
    """Decode a JSON response, translating failures into ``ParseError``."""
    try:
        return json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise ParseError(f'{source}: response from {response.url} is not JSON: {exc}') from exc
