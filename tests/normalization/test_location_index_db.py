"""The loaded index must agree with the packaged catalog, not just with itself."""

import pytest
from django.core.management import call_command

from core.locations.models import City, LocationAlias, Province, Region
from core.normalization import LocationIndex, normalize_detail

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(db):
    call_command('seed_locations')


def test_source_ids_resolve_to_the_seeded_hierarchy(seeded):
    index = LocationIndex.load()

    divar = index.resolve(place_refs=['22'], source='divar')
    assert divar.city_id == City.objects.get(code='sari').id
    assert divar.province_id == Province.objects.get(code='mazandaran').id

    sheypoor = index.resolve(place_refs=['nowshahr'], source='sheypoor')
    assert sheypoor.city_id == City.objects.get(code='nowshahr').id


def test_aliases_are_matched_after_folding(seeded):
    index = LocationIndex.load()

    # The seed file stores "بندر انزلى" with an Arabic yaa; a listing may write
    # either spelling, and both have to land on the same city.
    assert index.resolve(raw_location='بندر انزلی').city_id == (
        City.objects.get(code='bandar-anzali').id
    )
    assert (
        index.resolve(raw_location='هشتپر').city_id
        == LocationAlias.objects.get(alias='هشتپر').city_id
    )


def test_a_fixture_listing_resolves_end_to_end(seeded, sheypoor_detail):
    listing = normalize_detail(sheypoor_detail, index=LocationIndex.load())

    assert listing.province_id == Province.objects.get(code='mazandaran').id
    assert listing.city_id == City.objects.get(code='nowshahr').id
    assert listing.region_id == Region.objects.get(code='band-e-pey').id


def test_inactive_places_drop_out_of_the_index(seeded):
    sari = City.objects.get(code='sari')
    City.objects.filter(pk=sari.pk).update(is_active=False)

    index = LocationIndex.load()

    assert index.resolve(place_refs=['22'], source='divar').city_id is None
