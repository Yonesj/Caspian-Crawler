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
    RecordingLimiter,
    first_fixture,
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
    detail = fixture_json(first_fixture('divar_detail_*.json').name)

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
            200, text=first_fixture('divar_detail_*.json').read_text(encoding='utf-8')
        )
    )

    parsed = adapter.fetch_detail('gasGkf8r')

    assert route.called
    assert parsed.source_id == 'gasGkf8r'
    assert parsed.raw['seo']


@respx.mock
def test_detail_preserves_the_not_available_after_signal(adapter):
    detail = fixture_json(first_fixture('divar_detail_*.json').name)

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
