"""Shared fixtures for the crawl pipeline tests.

Everything here is offline: adapters are fakes, locations come from fixtures
built in the test database, and the real source payloads are the committed ones
under ``tests/sources/fixtures``.
"""

from types import SimpleNamespace

import pytest

from django.core.management import call_command

from core.crawling import models
from core.listings.enums import PropertyType, TransactionType
from core.locations.models import City, Province, Region, SourceLocation
from core.sources.dto import CrawlScope, ListPage, ListingDetail, ListingStub
from core.sources.enums import Source
from tests.sources.conftest import fixture_json


@pytest.fixture
def places(db):
    """A small hierarchy plus the source mappings the crawler resolves through."""
    province = Province.objects.create(
        code='mazandaran', name_fa='مازندران', name_en='Mazandaran'
    )
    city = City.objects.create(
        province=province, code='sari', name_fa='ساری', name_en='Sari'
    )
    region = Region.objects.create(
        city=city, code='farhang-shahr', name_fa='فرهنگشهر', name_en='Farhang Shahr'
    )
    SourceLocation.objects.create(
        source=Source.DIVAR, external_id='893', province=province
    )
    SourceLocation.objects.create(source=Source.DIVAR, external_id='22', city=city)
    SourceLocation.objects.create(
        source=Source.DIVAR, external_id='22-99', region=region
    )
    SourceLocation.objects.create(source=Source.SHEYPOOR, external_id='sari', city=city)
    return SimpleNamespace(province=province, city=city, region=region)


@pytest.fixture
def source_categories(db):
    """Seed the verified source category slugs from the packaged data file."""
    call_command('seed_source_categories', verbosity=0)


@pytest.fixture
def job_factory(places, source_categories):
    """Create jobs through the real service so scope resolution is exercised."""

    def make(*, source=Source.DIVAR, target='city', **overrides):
        location = {
            'province': {'province': places.province},
            'city': {'city': places.city},
            'region': {'region': places.region},
        }[target]
        kwargs = {
            'source': source,
            'transaction_type': TransactionType.SALE,
            'property_type': PropertyType.APARTMENT,
        }
        kwargs.update(location)
        kwargs.update(overrides)
        return models.create_job(**kwargs)

    return make


def make_stub(source_id, *, title='آپارتمان ۱۰۰ متری', url=None, **overrides):
    return ListingStub(
        source=Source.DIVAR,
        source_id=source_id,
        url=url or f'https://divar.ir/v/{source_id}',
        title=title,
        **overrides,
    )


def make_detail(source_id, **overrides):
    values = {
        'source': Source.DIVAR,
        'source_id': source_id,
        'url': f'https://divar.ir/v/{source_id}',
        'title': 'آپارتمان ۱۰۰ متری',
        'description': 'توضیحات آگهی',
        'raw_price': '۳,۰۰۰,۰۰۰,۰۰۰ تومان',
        'category_path': ('apartment-sell',),
        'attributes': {'متراژ': '۱۰۰', 'اتاق': '۲'},
        'image_urls': ['https://images.example/1.jpg'],
        'raw': {'id': source_id},
    }
    values.update(overrides)
    return ListingDetail(**values)


class FakeAdapter:
    """Adapter double: scripted pages, detail results or exceptions."""

    source = Source.DIVAR

    def __init__(self, details, *, pages=None, list_error=None):
        self._details = details
        self._pages = pages
        self._list_error = list_error
        self.detail_calls: list[str] = []

    def iter_list_pages(self, scope):
        if self._list_error is not None:
            raise self._list_error
        yield from self._pages or []

    def fetch_detail(self, source_id, *, url=None):
        self.detail_calls.append(source_id)
        result = self._details[source_id]
        if isinstance(result, Exception):
            raise result
        return result


def divar_fixture_details(*source_ids):
    """Real parsed Divar detail payloads, so fixtures stay on the path."""
    from core.sources.adapters import divar

    for source_id in source_ids:
        fixture = {
            'gar-qQRf': 'divar_detail_gar-qQRf.json',
            'gas6SGcg': 'divar_detail_gas6SGcg.json',
            'gasGkf8r': 'divar_detail_gasGkf8r.json',
        }[source_id]
        yield source_id, divar.parse_detail(fixture_json(fixture), source_id)


def page(*stubs, number=1, has_next=False):
    return ListPage(items=list(stubs), page=number, has_next_page=has_next)


__all__ = [
    'CrawlScope',
    'FakeAdapter',
    'divar_fixture_details',
    'make_detail',
    'make_stub',
    'page',
]
