import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.integration


def test_location_endpoints_return_active_hierarchy_and_honor_parent_filters(places):
    client = APIClient()

    provinces = client.get('/api/locations/provinces/')
    cities = client.get(
        '/api/locations/cities/', {'province': places.province.pk}
    )
    regions = client.get('/api/locations/regions/', {'city': places.city.pk})

    assert provinces.status_code == 200
    assert provinces.json() == [
        {
            'id': places.province.pk,
            'code': 'mazandaran',
            'name_fa': 'مازندران',
            'name_en': 'Mazandaran',
        }
    ]
    assert cities.json() == [
        {
            'id': places.city.pk,
            'province': places.province.pk,
            'code': 'sari',
            'name_fa': 'ساری',
            'name_en': 'Sari',
        }
    ]
    assert regions.json() == [
        {
            'id': places.region.pk,
            'city': places.city.pk,
            'code': 'farhang-shahr',
            'name_fa': 'فرهنگشهر',
            'name_en': 'Farhang Shahr',
        }
    ]


def test_location_endpoints_hide_inactive_rows(places):
    places.city.is_active = False
    places.city.save(update_fields=['is_active'])

    response = APIClient().get(
        '/api/locations/cities/', {'province': places.province.pk}
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    ('path', 'parameter'),
    [
        ('/api/locations/cities/', 'province'),
        ('/api/locations/regions/', 'city'),
    ],
)
def test_location_endpoints_reject_non_numeric_parent_filters(path, parameter):
    response = APIClient().get(path, {parameter: 'not-an-id'})

    assert response.status_code == 400
    assert parameter in response.json()
