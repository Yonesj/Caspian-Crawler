import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from core.locations.models import (
    City,
    LocationAlias,
    Province,
    Region,
    SourceLocation,
)
from core.sources.enums import Source

pytestmark = pytest.mark.integration


@pytest.fixture
def mazandaran(db):
    return Province.objects.create(
        code='mazandaran', name_fa='مازندران', name_en='Mazandaran'
    )


@pytest.fixture
def gilan(db):
    return Province.objects.create(code='gilan', name_fa='گیلان', name_en='Gilan')


@pytest.fixture
def sari(mazandaran):
    return City.objects.create(
        province=mazandaran, code='sari', name_fa='ساری', name_en='Sari'
    )


@pytest.fixture
def farhang_shahr(sari):
    return Region.objects.create(
        city=sari, code='farhang-shahr', name_fa='فرهنگشهر', name_en='Farhang Shahr'
    )


def test_city_code_is_unique_per_province_only(gilan, sari, mazandaran):
    City.objects.create(province=gilan, code='sari', name_fa='ساری', name_en='Sari')

    with pytest.raises(IntegrityError), transaction.atomic():
        City.objects.create(
            province=mazandaran, code='sari', name_fa='ساری', name_en='Sari'
        )


def test_location_target_returns_the_populated_level(farhang_shahr):
    region_only = SourceLocation.objects.create(
        source=Source.DIVAR, external_id='22', region=farhang_shahr
    )
    assert region_only.location_target() == farhang_shahr

    city_only = SourceLocation.objects.create(
        source=Source.SHEYPOOR, external_id='sari', city=farhang_shahr.city
    )
    assert city_only.location_target() == farhang_shahr.city


def test_source_location_requires_exactly_one_target(mazandaran, sari):
    with pytest.raises(IntegrityError), transaction.atomic():
        SourceLocation.objects.create(source=Source.DIVAR, external_id='1')

    with pytest.raises(IntegrityError), transaction.atomic():
        SourceLocation.objects.create(
            source=Source.DIVAR, external_id='2', province=mazandaran, city=sari
        )


def test_source_location_external_id_is_unique_per_source(mazandaran, sari):
    SourceLocation.objects.create(
        source=Source.DIVAR, external_id='22', province=mazandaran
    )

    # The same external id is meaningful for another source.
    SourceLocation.objects.create(
        source=Source.SHEYPOOR, external_id='22', city=sari
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        SourceLocation.objects.create(
            source=Source.DIVAR, external_id='22', city=sari
        )


def test_source_location_clean_rejects_city_from_another_province(gilan, sari):
    mapping = SourceLocation(
        source=Source.DIVAR, external_id='22', province=gilan, city=sari
    )

    with pytest.raises(ValidationError) as excinfo:
        mapping.full_clean()

    assert 'city' in excinfo.value.error_dict


def test_source_location_clean_rejects_region_without_its_city(
    mazandaran, farhang_shahr
):
    mapping = SourceLocation(
        source=Source.DIVAR, external_id='22', province=mazandaran, region=farhang_shahr
    )

    with pytest.raises(ValidationError) as excinfo:
        mapping.full_clean()

    assert 'city' in excinfo.value.error_dict


def test_location_alias_requires_exactly_one_target(sari):
    LocationAlias.objects.create(alias='ساری', city=sari)

    with pytest.raises(IntegrityError), transaction.atomic():
        LocationAlias.objects.create(alias='بدون مقصد')

    with pytest.raises(IntegrityError), transaction.atomic():
        LocationAlias.objects.create(alias='دو مقصد', city=sari, province=sari.province)


def test_location_alias_text_is_unique(sari):
    LocationAlias.objects.create(alias='ساری', city=sari)

    with pytest.raises(IntegrityError), transaction.atomic():
        LocationAlias.objects.create(alias='ساری', city=sari)
