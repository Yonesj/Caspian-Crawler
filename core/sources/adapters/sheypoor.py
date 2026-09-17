"""Sheypoor adapter.

Sheypoor serves a server-rendered Next.js page whose listings live in the React
Flight stream: ``self.__next_f.push([1,"<json string>"])`` chunks that, once
concatenated, form ``<hex id>:<payload>`` rows.  Listing fields frequently point
at other rows through ``"$id"`` references (price, images, attributes), so the
adapter rebuilds the row map and resolves those references.

Two quirks drive the parser's shape: rows are *not* reliably newline separated
(a text row can run straight into the next id), so rows are found by scanning
for an id followed by a JSON value and continuing after the value that
successfully decodes; and rows may carry a cap tag (``I``, ``HL``, ``T``) before
their payload.

URLs are the honest limit here: an id-only detail URL returns 404, so
``fetch_detail`` needs the URL the listing was discovered at.  Only
``/s/<slug>`` and ``?page_num=`` are requested, matching robots.txt, which
disallows ``/search``, ``/session``, ``/pro`` and bare query strings.
"""

import json
import re
from collections.abc import Iterator
from html import unescape
from typing import Any
from urllib.parse import quote, urlparse

from selectolax.parser import HTMLParser

from ..base import SourceAdapter
from ..dto import CrawlScope, ListingDetail, ListingStub, ListPage
from ..enums import Source
from ..errors import ParseError, SourceError
from ..transport import FetchRequest

LIST_URL = 'https://www.sheypoor.com/s/{slug}'
FLIGHT_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
ROW_START_RE = re.compile(r'([0-9a-f]{1,4}):')
REF_RE = re.compile(r'^\$([0-9a-f]{1,4})(?:\.(.+))?$')
LISTING_ID_RE = re.compile(r'-(\d+)\.html$')
MAX_REF_DEPTH = 8
PLACE_BREADCRUMB_TYPES = ('province', 'region', 'city', 'neighbourhood', 'district')


# -- flight decoding ----------------------------------------------------------
def decode_flight_payload(html: str) -> str:
    """Concatenate the page's flight chunks into the raw row stream."""
    chunks = FLIGHT_CHUNK_RE.findall(html)
    if not chunks:
        raise ParseError('sheypoor: no Next.js flight chunks found in the page')
    parts = []
    for chunk in chunks:
        try:
            parts.append(json.loads(chunk))
        except json.JSONDecodeError as exc:
            raise ParseError(f'sheypoor: undecodable flight chunk: {exc}') from exc
    return ''.join(parts)


def flight_rows_ordered(payload: str) -> list[tuple[str, str]]:
    """Return ``(row id, raw JSON text)`` pairs in stream order.

    Rows are found by scanning for an id followed by a JSON value and resuming
    after the value that decoded, which is what makes the parser survive text
    rows and missing newline separators.  Rows may carry a short cap tag
    (``I``, ``HL``, ``T``) before their payload, so up to two leading capital
    letters are skipped.
    """
    rows: list[tuple[str, str]] = []
    decoder = json.JSONDecoder()
    position = 0
    while True:
        match = ROW_START_RE.search(payload, position)
        if match is None:
            return rows

        start = match.end()
        for _ in range(2):
            if start < len(payload) and payload[start].isascii() and payload[start].isupper():
                start += 1
            else:
                break

        for candidate in (start, match.end()):
            try:
                _, value_end = decoder.raw_decode(payload, candidate)
            except json.JSONDecodeError:
                continue
            rows.append((match.group(1), payload[start:value_end]))
            position = value_end
            break
        else:
            position = match.end()


def parse_flight_rows(payload: str) -> dict[str, Any]:
    """Rebuild the ``id -> value`` row map from a flight row stream."""
    rows: dict[str, Any] = {}
    for row_id, raw_text in flight_rows_ordered(payload):
        try:
            rows[row_id] = json.loads(raw_text)
        except json.JSONDecodeError:  # pragma: no cover - guarded by the scanner
            continue
    if not rows:
        raise ParseError('sheypoor: could not decode any flight rows')
    return rows


def resolve_refs(value: Any, rows: dict[str, Any], depth: int = 0) -> Any:
    """Resolve ``"$id"`` references (and ``"$id.path"``) inside a value."""
    if depth >= MAX_REF_DEPTH:
        return value
    if isinstance(value, str):
        match = REF_RE.match(value)
        if match is None:
            return value
        target = rows.get(match.group(1))
        if match.group(2):
            for part in match.group(2).split('.'):
                if not isinstance(target, dict):
                    return None
                target = target.get(part)
        return resolve_refs(target, rows, depth + 1)
    if isinstance(value, list):
        return [resolve_refs(item, rows, depth + 1) for item in value]
    if isinstance(value, dict):
        return {key: resolve_refs(item, rows, depth + 1) for key, item in value.items()}
    return value


# -- field helpers ------------------------------------------------------------
def html_to_text(raw: str) -> str:
    """Strip the source's inline markup from a description."""
    if not raw:
        return ''
    try:
        text = HTMLParser(raw).text(separator=' ')
    except Exception:  # noqa: BLE001  # pragma: no cover - any parser failure falls back
        text = re.sub(r'<[^>]+>', ' ', raw)
    return re.sub(r'\s+', ' ', unescape(text)).strip()


def first_image_url(value: Any, depth: int = 0) -> str | None:
    """Return the first image URL found in a resolved structure."""
    if depth > 6:
        return None
    if isinstance(value, str):
        return value if value.startswith('http') else None
    if isinstance(value, list):
        for item in value:
            url = first_image_url(item, depth + 1)
            if url:
                return url
        return None
    if isinstance(value, dict):
        for key in ('original', 'url', 'landscape', 'round', 'source', 'thumbnails', 'image'):
            if key in value:
                url = first_image_url(value[key], depth + 1)
                if url:
                    return url
        for item in value.values():
            url = first_image_url(item, depth + 1)
            if url:
                return url
    return None


def format_price(value: Any) -> str | None:
    """Render a resolved price object as the source words it."""
    if isinstance(value, list):
        value = next((item for item in value if item), None)
    if isinstance(value, dict):
        amount = value.get('amount')
        currency = value.get('currency') or ''
        label = value.get('label')
        if amount in (None, ''):
            return f'{label} {currency}'.strip() or None
        return f'{amount} {currency}'.strip()
    if isinstance(value, str):
        return value.strip() or None
    return None


def path_segments(url: str) -> tuple[str, ...]:
    """Path segments of a site URL, without the leading ``s`` route prefix."""
    path = urlparse(url or '').path
    return tuple(segment for segment in path.split('/') if segment and segment != 's')


def breadcrumb_refs(breadcrumbs: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(category_path, place_refs)`` from a page's breadcrumbs.

    Categories keep the order they are published in (general to specific) and
    places come back most specific first.  A place breadcrumb's slug is its last
    path segment that is not itself a category segment, because a neighbourhood
    links to ``/s/<city>/<neighbourhood>/<category>``.
    """
    items = [item for item in (breadcrumbs or []) if isinstance(item, dict)]

    categories: list[str] = []
    for item in items:
        if item.get('type') != 'category':
            continue
        segments = path_segments(item.get('url') or '')
        if segments and segments[-1] not in categories:
            categories.append(segments[-1])

    places: list[str] = []
    for item in reversed(items):
        if item.get('type') not in PLACE_BREADCRUMB_TYPES:
            continue
        segments = tuple(
            segment
            for segment in path_segments(item.get('url') or '')
            if segment not in categories
        )
        if segments and segments[-1] not in places:
            places.append(segments[-1])

    return tuple(categories), tuple(places)


def source_id_from_url(url: str) -> str | None:
    match = LISTING_ID_RE.search(url or '')
    return match.group(1) if match else None


def is_listing(value: Any) -> bool:
    """Shape test: listing objects carry a /v/ URL, a title and a price."""
    return (
        isinstance(value, dict)
        and isinstance(value.get('url'), str)
        and '/v/' in value['url']
        and isinstance(value.get('title'), str)
        and ('price' in value or 'location' in value)
    )


def listing_rows(rows: dict[str, Any]) -> Iterator[dict]:
    for value in rows.values():
        if is_listing(value):
            yield value


def stub_from_row(row: dict, rows: dict[str, Any]) -> ListingStub | None:
    source_id = str(row.get('id') or source_id_from_url(row.get('url', '')) or '')
    if not source_id:
        return None
    return ListingStub(
        source=Source.SHEYPOOR,
        source_id=source_id,
        url=row['url'],
        title=row['title'].strip(),
        raw_price=format_price(resolve_refs(row.get('price'), rows)),
        raw_location=str(row.get('location') or ''),
        image_url=first_image_url(resolve_refs(row.get('images'), rows)),
        extra={
            'category_id': row.get('categoryId'),
            'top_category_id': row.get('topCategoryId'),
            'time_passed_label': row.get('timePassedLabel'),
            'image_count': row.get('imageCount'),
        },
    )


# -- payload parsing ----------------------------------------------------------
def parse_list_page(html: str, scope: CrawlScope, page: int) -> ListPage:
    rows = parse_flight_rows(decode_flight_payload(html))

    items = []
    seen: set[str] = set()
    for row in listing_rows(rows):
        stub = stub_from_row(row, rows)
        if stub is None or stub.source_id in seen:
            continue
        seen.add(stub.source_id)
        items.append(stub)

    if not items:
        raise ParseError(f'sheypoor: page {page} contained no listings')

    has_next_page = f'page_num={page + 1}' in html
    return ListPage(items=items, page=page, has_next_page=has_next_page, raw={})


def parse_detail(html: str, source_id: str, url: str) -> ListingDetail:
    rows = parse_flight_rows(decode_flight_payload(html))

    row = next(
        (
            value
            for value in rows.values()
            if isinstance(value, dict) and value.get('type') == 'publicListingDetails'
        ),
        None,
    )
    if row is None:
        raise ParseError(f'sheypoor: no listing detail row found at {url}')

    attributes = {}
    for item in resolve_refs(row.get('attributes'), rows) or []:
        if isinstance(item, dict) and item.get('key'):
            attributes[str(item['key'])] = str(item.get('value', ''))

    image_urls: list[str] = []
    for item in resolve_refs(row.get('images'), rows) or []:
        image_url = first_image_url(item)
        if image_url and image_url not in image_urls:
            image_urls.append(image_url)

    breadcrumbs = resolve_refs(row.get('breadcrumbs'), rows) or []
    category_path, place_refs = breadcrumb_refs(breadcrumbs)

    return ListingDetail(
        source=Source.SHEYPOOR,
        source_id=str(row.get('id') or source_id),
        url=row.get('url') or url,
        title=str(row.get('title') or '').strip(),
        description=html_to_text(str(resolve_refs(row.get('description'), rows) or '')),
        raw_location=str(row.get('location') or ''),
        raw_price=format_price(resolve_refs(row.get('price'), rows)),
        attributes=attributes,
        image_urls=image_urls,
        published_at_text=row.get('addedAt'),
        category_path=category_path,
        place_refs=place_refs,
        raw={
            'category_id': row.get('categoryId'),
            'top_category_id': row.get('topCategoryId'),
            'breadcrumbs': breadcrumbs,
            'time_passed_label': row.get('timePassedLabel'),
        },
    )


class SheypoorAdapter(SourceAdapter):
    source = Source.SHEYPOOR

    def iter_list_pages(self, scope: CrawlScope) -> Iterator[ListPage]:
        page = 1
        previous_ids: set[str] | None = None
        while True:
            request_kwargs = {'source': self.source}
            if page > 1:
                request_kwargs['params'] = {'page_num': page}
            response = self.fetcher.fetch(
                FetchRequest(
                    method='GET',
                    url=LIST_URL.format(slug=quote(str(scope.external_id))),
                    **request_kwargs,
                )
            )
            list_page = parse_list_page(response.text, scope, page)
            page_ids = {item.source_id for item in list_page.items}
            if page_ids == previous_ids:
                # Defensive: the source ignored page_num and repeated itself.
                return
            previous_ids = page_ids
            yield list_page

            if not list_page.has_next_page:
                return
            if scope.page_limit is not None and page >= scope.page_limit:
                return
            page += 1

    def fetch_detail(self, source_id: str, *, url: str | None = None) -> ListingDetail:
        if not url:
            raise SourceError(
                f'sheypoor: detail urls are slugged, so a url is required for {source_id}'
            )
        response = self.fetcher.fetch(
            FetchRequest(method='GET', url=url, source=self.source)
        )
        return parse_detail(response.text, source_id, url)
