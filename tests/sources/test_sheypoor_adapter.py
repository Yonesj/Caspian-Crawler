import httpx
import pytest
import respx

from core.sources.adapters import sheypoor
from core.sources.adapters.sheypoor import SheypoorAdapter
from core.sources.dto import CrawlScope
from core.sources.enums import Source
from core.sources.errors import ParseError, SourceError
from core.sources.transport import HttpxFetcher
from tests.sources.conftest import (
    RecordingLimiter,
    first_fixture,
    fixture_text,
)

SCOPE = CrawlScope(external_id='mazandaran', label='Mazandaran')


@pytest.fixture
def adapter(clock, rng):
    return SheypoorAdapter(
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
    respx.get(sheypoor.LIST_URL.format(slug='mazandaran')).mock(
        return_value=httpx.Response(200, text=fixture_text('sheypoor_list_page1.html'))
    )

    pages = list(adapter.iter_list_pages(CrawlScope(SCOPE.external_id, page_limit=1)))

    stubs = pages[0].items
    assert [stub.source_id for stub in stubs] == [
        '467056385', '464398666', '464167565', '467423760',
    ]
    first = stubs[0]
    assert first.source == Source.SHEYPOOR
    assert first.url.startswith('https://www.sheypoor.com/v/')
    assert first.raw_price == '3,100,000,000 تومان'
    assert first.raw_location == 'ملارد، دهستان اختر آباد'
    assert first.image_url.startswith('https://cdn.sheypoor.com/')
    # "توافقی" (negotiable) survives as text rather than becoming a number.
    assert stubs[1].raw_price == 'توافقی'


@respx.mock
def test_pagination_uses_page_num_and_stops_when_a_page_repeats(adapter):
    requests = []

    def handler(request):
        requests.append(request.url)
        return httpx.Response(200, text=fixture_text('sheypoor_list_page1.html'))

    respx.get(url__startswith=sheypoor.LIST_URL.format(slug='mazandaran')).mock(
        side_effect=handler
    )

    pages = list(adapter.iter_list_pages(SCOPE))

    # The trimmed fixture has no page_num link, so iteration stops after page 1.
    assert len(pages) == 1
    assert len(requests) == 1


@respx.mock
def test_next_page_link_continues_to_the_next_page(adapter):
    first = fixture_text('sheypoor_list_page1.html')
    with_link = first.replace('</body>', '<a href="?page_num=2">next</a></body>')
    # A genuinely different second page: one listing id changed.
    second = with_link.replace('-467056385.html', '-999999999.html')
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text=with_link if len(calls) == 1 else second)

    respx.get(url__startswith=sheypoor.LIST_URL.format(slug='mazandaran')).mock(
        side_effect=handler
    )

    pages = list(adapter.iter_list_pages(SCOPE))

    assert [page.page for page in pages] == [1, 2]
    assert 'page_num=2' in calls[1]
    assert pages[1].items[0].source_id == '999999999'


@respx.mock
def test_repeated_page_stops_the_loop(adapter):
    repeated = fixture_text('sheypoor_list_page1.html').replace(
        '</body>', '<a href="?page_num=2">next</a></body>'
    )
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text=repeated)

    respx.get(url__startswith=sheypoor.LIST_URL.format(slug='mazandaran')).mock(
        side_effect=handler
    )

    pages = list(adapter.iter_list_pages(SCOPE))

    # The source ignored page_num and repeated itself, so the adapter stopped
    # after one yielded page instead of looping forever.
    assert len(pages) == 1
    assert len(calls) == 2


@pytest.fixture
def detail_html():
    return first_fixture('sheypoor_detail_*.html').read_text(encoding='utf-8')


def test_detail_page_is_parsed(detail_html):
    parsed = sheypoor.parse_detail(detail_html, '464398666', 'https://example.test/v/x.html')

    assert parsed.source == Source.SHEYPOOR
    assert parsed.source_id == '464398666'
    assert parsed.attributes['متراژ'] == '۹۵۰'
    assert parsed.attributes['نوع کاربری'] == 'مسکونی'
    assert len(parsed.image_urls) >= 2
    assert parsed.image_urls[0].startswith('https://')
    assert '<' not in parsed.description and parsed.description
    assert parsed.published_at_text.startswith('2026-')
    assert parsed.raw_location


@respx.mock
def test_fetch_detail_needs_the_slugged_url(adapter, detail_html):
    with pytest.raises(SourceError):
        adapter.fetch_detail('464398666')

    respx.get('https://www.sheypoor.com/v/x.html').mock(
        return_value=httpx.Response(200, text=detail_html)
    )
    parsed = adapter.fetch_detail('464398666', url='https://www.sheypoor.com/v/x.html')
    assert parsed.source_id == '464398666'


def test_page_without_flight_chunks_is_a_parse_error():
    with pytest.raises(ParseError):
        sheypoor.parse_list_page('<html><body>nope</body></html>', SCOPE, 1)


def test_page_without_listings_is_a_parse_error():
    html = (
        '<html><body><script>self.__next_f.push([1,"1:{\\"a\\":1}\\n"])</script>'
        '</body></html>'
    )

    with pytest.raises(ParseError):
        sheypoor.parse_list_page(html, SCOPE, 1)


def test_flight_rows_survive_missing_newline_separators():
    stream = '1:Tمتن بدون جداکننده2:{"a":1}\n3:{"b":2}\n'

    rows = sheypoor.parse_flight_rows(stream)

    assert rows == {'2': {'a': 1}, '3': {'b': 2}}


def test_flight_rows_skip_cap_tags():
    stream = '1:I[68260,["a"]]\n2:HL["/x.woff"]\n3:{"a":1}\n'

    rows = sheypoor.parse_flight_rows(stream)

    assert rows['3'] == {'a': 1}


def test_flight_rows_without_any_json_is_an_error():
    with pytest.raises(ParseError):
        sheypoor.parse_flight_rows('1:Tفقط متن است')


def test_references_resolve_through_rows():
    rows = {'1': {'amount': 100}, '2': ['$1'], '3': {'price': '$2'}}

    assert sheypoor.resolve_refs('$1', rows) == {'amount': 100}
    assert sheypoor.resolve_refs('$3.price', rows) == [{'amount': 100}]
    assert sheypoor.resolve_refs('$9', rows) is None
    assert sheypoor.resolve_refs('plain', rows) == 'plain'


def test_price_and_image_helpers():
    rows = {
        '10': {'amount': '3,100,000,000', 'currency': 'تومان'},
        '11': {'thumbnails': {'round': 'https://cdn/thumb.webp'}},
    }

    assert sheypoor.format_price(sheypoor.resolve_refs('$10', rows)) == '3,100,000,000 تومان'
    assert sheypoor.format_price({'label': 'توافقی'}) == 'توافقی'
    assert sheypoor.format_price(None) is None
    assert (
        sheypoor.first_image_url(sheypoor.resolve_refs('$11', rows))
        == 'https://cdn/thumb.webp'
    )


@pytest.mark.parametrize(
    'url,expected',
    [
        ('https://www.sheypoor.com/v/فروش-ویلا-464855066.html', '464855066'),
        ('https://www.sheypoor.com/v/no-id.html', None),
        ('', None),
    ],
)
def test_source_id_from_url(url, expected):
    assert sheypoor.source_id_from_url(url) == expected
