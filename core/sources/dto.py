"""Source-shaped data transfer objects.

These carry the values a source publishes, *before* normalization: prices stay
raw strings such as ``"۶,۹۵۰,۰۰۰,۰۰۰ تومان"`` and dates stay whatever the source
printed.  Turning them into Decimals, Toman and UTC timestamps is the
normalization layer's job, which keeps source parsing and semantic conversion
independently testable.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CrawlScope:
    """Where to crawl.

    ``external_id`` is the source's own identifier for the place: Divar's
    numeric place id (``"22"``) or Sheypoor's path slug (``"mazandaran"``).  How
    a local city maps onto it is reference data (``SourceLocation``), not code.
    """

    external_id: str
    label: str = ''
    page_limit: int | None = None

    def __post_init__(self):
        if not self.external_id:
            raise ValueError('CrawlScope.external_id is required')
        if self.page_limit is not None and self.page_limit < 1:
            raise ValueError('CrawlScope.page_limit must be >= 1 when set')


@dataclass(frozen=True)
class ListingStub:
    """A listing as it appears on a search/list page."""

    source: str
    source_id: str
    url: str
    title: str
    raw_price: str | None = None
    raw_location: str = ''
    image_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ListingDetail:
    """Everything the source's detail page exposes for one listing."""

    source: str
    source_id: str
    url: str
    title: str
    description: str = ''
    raw_location: str = ''
    raw_price: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    image_urls: list[str] = field(default_factory=list)
    published_at_text: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ListPage:
    """One page of listings plus the state needed to fetch the next one."""

    items: list[ListingStub]
    page: int
    has_next_page: bool
    raw: dict[str, Any] = field(default_factory=dict)
