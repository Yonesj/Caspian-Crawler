"""Shared fixtures for the normalization tests.

Normalization is deliberately database-free, so the location index used here is
built from plain dictionaries.  A separate integration test checks that
``LocationIndex.load()`` produces the same thing from the real tables.
"""

import pytest

from core.normalization import LocationIndex
from tests.sources.conftest import fixture_json, fixture_text

# A miniature catalog with real ids where they are known: Sari is Divar's city
# 22, Nowshahr is Sheypoor's "nowshahr" and Band-e Pey its "band-e-pey".
PROVINCES = [
    {'id': 1, 'name_fa': 'مازندران'},
    {'id': 2, 'name_fa': 'گیلان'},
]
CITIES = [
    {'id': 22, 'name_fa': 'ساری', 'province_id': 1},
    {'id': 23, 'name_fa': 'نوشهر', 'province_id': 1},
    {'id': 24, 'name_fa': 'بندر انزلی', 'province_id': 2},
]
REGIONS = [{'id': 31, 'name_fa': 'بندپی', 'city_id': 23}]
ALIASES = [
    {'alias': 'سارى', 'level': 'city', 'id': 22},
    {'alias': 'بندر انزلى', 'level': 'city', 'id': 24},
    {'alias': 'مازندران', 'level': 'province', 'id': 1},
]
SOURCE_LOCATIONS = [
    {'source': 'divar', 'external_id': '22', 'level': 'city', 'id': 22},
    {'source': 'sheypoor', 'external_id': 'nowshahr', 'level': 'city', 'id': 23},
    {'source': 'sheypoor', 'external_id': 'band-e-pey', 'level': 'region', 'id': 31},
]


@pytest.fixture
def index():
    return LocationIndex(
        provinces=PROVINCES,
        cities=CITIES,
        regions=REGIONS,
        aliases=ALIASES,
        source_locations=SOURCE_LOCATIONS,
    )


@pytest.fixture
def divar_sale_detail():
    from core.sources.adapters import divar

    payload = fixture_json('divar_detail_gar-qQRf.json')
    return divar.parse_detail(payload, 'gar-qQRf')


@pytest.fixture
def divar_rent_detail():
    from core.sources.adapters import divar

    payload = fixture_json('divar_detail_gas6SGcg.json')
    return divar.parse_detail(payload, 'gas6SGcg')


@pytest.fixture
def sheypoor_detail():
    from core.sources.adapters import sheypoor

    html = fixture_text('sheypoor_detail_464398666.html')
    return sheypoor.parse_detail(html, '464398666', 'https://www.sheypoor.com/v/x.html')
