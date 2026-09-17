import json

import httpx
import pytest
import respx

from core.sources.adapters import divar
from core.sources.adapters.divar import DivarAdapter
from core.sources.dto import CrawlScope
from core.sources.enums import Source
from core.sources.errors import ParseError
from core.sources.transport import HttpxFetcher
from tests.sources.conftest import (
    DIVAR_APARTMENT_RENT,
    DIVAR_APARTMENT_SALE,
    DIVAR_COMMERCIAL_RENT,
    RecordingLimiter,
    fixture_json,
    fixture_text,
)

SCOPE = CrawlScope(external_id='22', label='Sari')


@pytest.fixture
def adapter(clock, rng):
    return DivarAdapter(
        fetcher=HttpxFetcher(
            client=httpx.Client(),
            limiter=RecordingLimiter(),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            rng=rng,
            jitter_ratio=0.0,
            user_agent='NorthEstate/test',
        )
    )


@respx.mock
def test_list_page_is_parsed_into_stubs(adapter):
    respx.post(divar.LIST_URL).mock(
        return_value=httpx.Response(200, text=fixture_text('divar_list_page1.json'))
    )

    pages = list(adapter.iter_list_pages(CrawlScope(SCOPE.external_id, page_limit=1)))

    assert len(pages) == 1
    stubs = pages[0].items
    assert [stub.source_id for stub in stubs] == ['gapqVBMq', 'gasGUrho', 'gasGkf8r', 'gasC0_jt']
    first = stubs[0]
    assert first.source == Source.DIVAR
    assert first.url == 'https://divar.ir/v/gapqVBMq'
    assert first.raw_price == '۱۰۰,۰۰۰,۰۰۰ تومان'
    assert first.raw_location == 'ساری'
    assert first.image_url.startswith('https://')


@respx.mock
def test_pagination_echoes_the_cursor_and_stops(adapter):
    fixture = fixture_json('divar_list_page1.json')
    requested_bodies = []

    def handler(request):
        body = json.loads(request.content)
        requested_bodies.append(body)
        if 'pagination_data' in body:
            return httpx.Response(
                200,
                json={
                    'list_widgets': [
                        {
                            'widget_type': 'POST_ROW',
                            'data': {
                                'title': 'آخرین صفحه',
                                'action': {'payload': {'token': 'lastpage1'}},
                            },
                        }
                    ],
                    'pagination': {'has_next_page': False},
                },
            )
        return httpx.Response(200, json=fixture)

    respx.post(divar.LIST_URL).mock(side_effect=handler)

    pages = list(adapter.iter_list_pages(SCOPE))

    assert [page.page for page in pages] == [1, 2]
    assert pages[1].items[0].source_id == 'lastpage1'
    assert 'pagination_data' not in requested_bodies[0]
    assert requested_bodies[1]['pagination_data'] == fixture['pagination']['data']


@respx.mock
def test_page_limit_stops_early(adapter):
    route = respx.post(divar.LIST_URL).mock(
        return_value=httpx.Response(200, text=fixture_text('divar_list_page1.json'))
    )

    pages = list(adapter.iter_list_pages(CrawlScope(SCOPE.external_id, page_limit=1)))

    assert len(pages) == 1
    assert route.call_count == 1


@respx.mock
def test_detail_page_is_parsed(adapter):
    detail = fixture_json(DIVAR_COMMERCIAL_RENT)

    parsed = divar.parse_detail(detail, 'gasGkf8r')

    assert parsed.source == Source.DIVAR
    assert parsed.title == 'اجاره مغازه'
    assert parsed.attributes['متراژ'] == '۱۲'
    assert parsed.attributes['اتاق'] == 'بدون اتاق'
    assert parsed.raw_location == 'ساری'
    assert parsed.image_urls and parsed.image_urls[0].startswith('https://')
    assert parsed.published_at_text.startswith('انتشار آگهی')
    assert parsed.url.startswith('https://divar.ir/v/')


@respx.mock
def test_fetch_detail_requests_the_token_endpoint(adapter):
    route = respx.get(divar.DETAIL_URL.format(token='gasGkf8r')).mock(
        return_value=httpx.Response(
            200, text=fixture_text(DIVAR_COMMERCIAL_RENT)
        )
    )

    parsed = adapter.fetch_detail('gasGkf8r')

    assert route.called
    assert parsed.source_id == 'gasGkf8r'
    assert parsed.raw['seo']


@respx.mock
def test_detail_preserves_the_not_available_after_signal(adapter):
    detail = fixture_json(DIVAR_COMMERCIAL_RENT)

    parsed = divar.parse_detail(detail, 'gasGkf8r')

    assert 'unavailable_after' in parsed.raw['seo']


def test_missing_list_widgets_is_a_parse_error():
    with pytest.raises(ParseError):
        divar.parse_list_page({'nope': []}, SCOPE, 1)


def test_row_without_a_token_is_a_parse_error():
    payload = {'list_widgets': [{'widget_type': 'POST_ROW', 'data': {'title': 'x'}}]}

    with pytest.raises(ParseError):
        divar.parse_list_page(payload, SCOPE, 1)


def test_missing_sections_is_a_parse_error():
    with pytest.raises(ParseError):
        divar.parse_detail({'seo': {}}, 'token')


@respx.mock
def test_iter_listings_flattens_pages(adapter):
    respx.post(divar.LIST_URL).mock(
        return_value=httpx.Response(200, text=fixture_text('divar_list_page1.json'))
    )

    stubs = list(adapter.iter_listings(CrawlScope(SCOPE.external_id, page_limit=1)))

    assert len(stubs) == 4


def test_detail_surfaces_the_source_category_and_place():
    detail = divar.parse_detail(fixture_json(DIVAR_APARTMENT_SALE), 'gar-qQRf')

    # General to specific, exactly as the site's own breadcrumbs nest them.
    assert detail.category_path == (
        'real-estate',
        'residential-sell',
        'apartment-sell',
    )
    assert detail.place_refs == ('22', 'sari')


def test_a_rent_detail_carries_its_own_category():
    detail = divar.parse_detail(fixture_json(DIVAR_APARTMENT_RENT), 'gas6SGcg')

    assert detail.category_path[-1] == 'apartment-rent'


def test_category_path_falls_back_to_the_schema_when_breadcrumbs_are_missing():
    payload = {'seo': {'post_seo_schema': {'category': 'shop-rent'}}}

    assert divar.category_path_from(payload['seo']) == ('shop-rent',)
    assert divar.category_path_from({}) == ()


def test_a_category_scope_is_sent_the_way_the_site_itself_does():
    unscoped = divar.list_body(CrawlScope('22'))
    scoped = divar.list_body(CrawlScope('22', category='apartment-sell'))

    assert 'search_data' not in unscoped
    assert scoped['search_data']['form_data']['data']['category']['str']['value'] == (
        'apartment-sell'
    )
    # Pagination and the category filter coexist: the filter is not dropped
    # when a follow-up page is requested.
    paged = divar.list_body(CrawlScope('22', category='apartment-sell'), {'page': 2})
    assert paged['pagination_data'] == {'page': 2}
    assert 'category' in paged['search_data']['form_data']['data']


@respx.mock
def test_the_list_request_carries_the_category(adapter):
    route = respx.post(divar.LIST_URL).mock(
        return_value=httpx.Response(
            200, text=fixture_text('divar_list_page1.json')
        )
    )

    list(
        adapter.iter_list_pages(
            CrawlScope('22', category='apartment-sell', page_limit=1)
        )
    )

    sent = json.loads(route.calls[0].request.content)
    assert sent['search_data']['form_data']['data']['category']['str']['value'] == (
        'apartment-sell'
    )
