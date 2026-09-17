"""Divar adapter.

Divar publishes the same JSON its own web client consumes:

* list:   ``POST https://api.divar.ir/v8/postlist/w/search``
* detail: ``GET  https://api.divar.ir/v8/posts-v2/web/<token>``

Pagination is cursor based: the ``pagination.data`` object from one response is
sent back verbatim as ``pagination_data`` to obtain the next page, and crawling
stops when ``pagination.has_next_page`` turns false.  (Verified live: pages 1,
2 and 3 have zero overlap.)  The older ``/v5/*`` endpoints answer 403, so only
``/v8/*`` is used.
"""

from collections.abc import Iterator
from typing import Any

from ..base import SourceAdapter, load_json
from ..dto import CrawlScope, ListingDetail, ListingStub, ListPage
from ..enums import Source
from ..errors import ParseError
from ..transport import FetchRequest

LIST_URL = 'https://api.divar.ir/v8/postlist/w/search'
DETAIL_URL = 'https://api.divar.ir/v8/posts-v2/web/{token}'
WEB_URL = 'https://divar.ir/v/{token}'

ROW_WIDGET = 'POST_ROW'
TITLE_WIDGETS = ('LEGEND_TITLE_ROW', 'TITLE_ROW')
DESCRIPTION_WIDGET = 'DESCRIPTION_ROW'
IMAGE_WIDGET = 'IMAGE_CAROUSEL'
ATTRIBUTE_WIDGETS = ('GROUP_INFO_ROW', 'LIST_DATA_ROW', 'UNEXPANDABLE_ROW')


def iter_widgets(sections: Any) -> Iterator[dict]:
    """Yield every widget, descending into expandable sections."""
    if not isinstance(sections, list):
        raise ParseError('divar: detail payload has no sections list')
    for section in sections:
        if not isinstance(section, dict):
            continue
        stack = list(section.get('widgets') or [])
        while stack:
            widget = stack.pop(0)
            if not isinstance(widget, dict):
                continue
            yield widget
            data = widget.get('data')
            if isinstance(data, dict) and isinstance(data.get('widget_list'), list):
                stack = list(data['widget_list']) + stack


def parse_list_page(payload: Any, scope: CrawlScope, page: int) -> ListPage:
    if not isinstance(payload, dict) or not isinstance(payload.get('list_widgets'), list):
        raise ParseError('divar: list payload has no list_widgets array')

    items = []
    for widget in payload['list_widgets']:
        if not isinstance(widget, dict) or widget.get('widget_type') != ROW_WIDGET:
            continue
        data = widget.get('data') or {}
        action_payload = (data.get('action') or {}).get('payload') or {}
        token = action_payload.get('token') or data.get('token')
        if not token:
            raise ParseError('divar: POST_ROW widget without a token')
        web_info = action_payload.get('web_info') or {}
        items.append(
            ListingStub(
                source=Source.DIVAR,
                source_id=str(token),
                url=WEB_URL.format(token=token),
                title=(data.get('title') or web_info.get('title') or '').strip(),
                raw_price=data.get('middle_description_text'),
                raw_location=web_info.get('city_persian') or '',
                image_url=data.get('image_url'),
                extra={
                    'image_count': data.get('image_count'),
                    'badge': data.get('red_text'),
                    'layout_type': data.get('layout_type'),
                },
            )
        )

    pagination = payload.get('pagination') or {}
    has_next_page = bool(pagination.get('has_next_page'))
    pagination_data = pagination.get('data')
    if has_next_page and not isinstance(pagination_data, dict):
        raise ParseError('divar: page claims a next page but sent no pagination data')
    return ListPage(
        items=items,
        page=page,
        has_next_page=has_next_page,
        raw={'pagination_data': pagination_data},
    )


def parse_detail(payload: Any, source_id: str) -> ListingDetail:
    if not isinstance(payload, dict):
        raise ParseError('divar: detail payload is not an object')

    seo = payload.get('seo') or {}
    web_info = seo.get('web_info') or {}
    schema = seo.get('post_seo_schema') or {}

    title = ''
    description_parts = []
    published_at_text = None
    date_block = None
    attributes: dict[str, str] = {}
    image_urls: list[str] = []

    for widget in iter_widgets(payload.get('sections')):
        widget_type = widget.get('widget_type')
        data = widget.get('data') or {}

        if not title and widget_type in TITLE_WIDGETS:
            title = str(data.get('title') or data.get('text') or '').strip()

        if widget_type == DESCRIPTION_WIDGET:
            text = str(data.get('text') or '').strip()
            if text:
                if 'انتشار' in text and published_at_text is None:
                    # The block also lists bump/update lines; the first line is
                    # the publication stamp and the rest is kept in ``raw``.
                    published_at_text = text.splitlines()[0].strip()
                    date_block = text
                else:
                    description_parts.append(text)

        if widget_type == IMAGE_WIDGET and isinstance(data.get('items'), list):
            for item in data['items']:
                if not isinstance(item, dict):
                    continue
                image = item.get('image') or {}
                url = image.get('url') if isinstance(image, dict) else None
                if isinstance(url, str) and url not in image_urls:
                    image_urls.append(url)

        if widget_type in ATTRIBUTE_WIDGETS:
            pairs = []
            if isinstance(data.get('items'), list):
                pairs = [item for item in data['items'] if isinstance(item, dict)]
            elif data.get('title') and data.get('value'):
                pairs = [data]
            for item in pairs:
                if item.get('title') and item.get('value'):
                    attributes.setdefault(str(item['title']), str(item['value']))

    return ListingDetail(
        source=Source.DIVAR,
        source_id=source_id,
        url=schema.get('url') or WEB_URL.format(token=source_id),
        title=title or str(web_info.get('title') or '').strip(),
        description='\n\n'.join(description_parts),
        raw_location=web_info.get('city_persian') or '',
        raw_price=attributes.get('قیمت کل') or attributes.get('قیمت'),
        attributes=attributes,
        image_urls=image_urls,
        published_at_text=published_at_text,
        raw={
            'seo': seo,
            'dates_text': date_block,
            'section_names': [s.get('section_name') for s in payload.get('sections') or []],
        },
    )


class DivarAdapter(SourceAdapter):
    source = Source.DIVAR

    def iter_list_pages(self, scope: CrawlScope) -> Iterator[ListPage]:
        body: dict[str, Any] = {'city_ids': [str(scope.external_id)]}
        page = 1
        while True:
            response = self.fetcher.fetch(
                FetchRequest(
                    method='POST',
                    url=LIST_URL,
                    source=self.source,
                    json_body=body,
                )
            )
            list_page = parse_list_page(load_json(response, self.source), scope, page)
            yield list_page

            if not list_page.has_next_page:
                return
            if scope.page_limit is not None and page >= scope.page_limit:
                return
            body = {**body, 'pagination_data': list_page.raw['pagination_data']}
            page += 1

    def fetch_detail(self, source_id: str, *, url: str | None = None) -> ListingDetail:
        response = self.fetcher.fetch(
            FetchRequest(
                method='GET',
                url=DETAIL_URL.format(token=source_id),
                source=self.source,
            )
        )
        return parse_detail(load_json(response, self.source), source_id)
