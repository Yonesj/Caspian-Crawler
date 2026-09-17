"""Fixtures shared by the integration suites.

The crawl pipeline, the lifecycle sweep and duplicate detection all need the
same starting point: a small location hierarchy with the source mappings and
category slugs the pipeline resolves through.
"""

from types import SimpleNamespace

import pytest
from django.core.management import call_command

from core.crawling import models
from core.listings.enums import PropertyType, TransactionType
from core.locations.models import City, Province, Region, SourceLocation
from core.sources.enums import Source


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
