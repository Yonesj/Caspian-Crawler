import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.listings.enums import ListingStatus, PropertyType, TransactionType
from core.listings.models import ListingImage
from tests.listings.helpers import make_listing

pytestmark = pytest.mark.integration


def test_listing_list_is_public_active_only_and_source_independent(places):
    active = make_listing(
        places,
        source_id='active',
        title='ویلای دریایی',
        description='نزدیک ساحل',
        area_sqm=120,
        sale_price=8_000_000_000,
    )
    make_listing(places, source_id='stale', status=ListingStatus.STALE)
    ListingImage.objects.create(
        listing=active, url='https://example.com/home.jpg', position=0
    )

    response = APIClient().get('/api/listings/')

    assert response.status_code == 200
    payload = response.json()
    assert payload['count'] == 1
    row = payload['results'][0]
    assert row['id'] == active.pk
    assert row['location']['city']['code'] == 'sari'
    assert row['prices']['sale'] == '8000000000'
    assert row['images'] == ['https://example.com/home.jpg']
    assert 'raw_data' not in row
    assert 'duplicate_of' not in row
    assert row['source_id'] == 'active'


def test_listing_list_filters_searches_and_orders_normalized_fields(places):
    smaller = make_listing(
        places,
        source_id='smaller',
        title='آپارتمان مرکز شهر',
        transaction_type=TransactionType.SALE,
        property_type=PropertyType.APARTMENT,
        area_sqm=80,
        sale_price=4_000_000_000,
    )
    larger = make_listing(
        places,
        source_id='larger',
        title='آپارتمان مرکز شهر بزرگ',
        transaction_type=TransactionType.SALE,
        property_type=PropertyType.APARTMENT,
        area_sqm=130,
        sale_price=9_000_000_000,
    )
    make_listing(
        places,
        source_id='rent',
        title='آپارتمان اجارهای',
        transaction_type=TransactionType.RENT,
    )

    response = APIClient().get(
        '/api/listings/',
        {
            'transaction_type': 'sale',
            'city': places.city.pk,
            'min_area': 75,
            'max_area': 140,
            'min_sale_price': 3_000_000_000,
            'search': 'مرکز',
            'ordering': '-area_sqm',
        },
    )

    assert response.status_code == 200
    assert [row['id'] for row in response.json()['results']] == [larger.pk, smaller.pk]


def test_only_staff_can_include_non_active_listings(places):
    active = make_listing(places, source_id='active')
    stale = make_listing(places, source_id='stale', status=ListingStatus.STALE)
    ordinary = get_user_model().objects.create_user(username='reader')
    staff = get_user_model().objects.create_user(username='staff', is_staff=True)

    ordinary_client = APIClient()
    ordinary_client.force_authenticate(ordinary)
    staff_client = APIClient()
    staff_client.force_authenticate(staff)

    ordinary_response = ordinary_client.get('/api/listings/', {'status': 'stale'})
    ordinary_detail_response = ordinary_client.get(f'/api/listings/{stale.pk}/')
    staff_default_response = staff_client.get('/api/listings/')
    staff_response = staff_client.get('/api/listings/', {'status': 'stale'})
    staff_detail_response = staff_client.get(f'/api/listings/{stale.pk}/')

    assert ordinary_response.json()['count'] == 0
    assert ordinary_detail_response.status_code == 404
    assert [row['id'] for row in staff_default_response.json()['results']] == [
        active.pk
    ]
    assert [row['id'] for row in staff_response.json()['results']] == [stale.pk]
    assert staff_detail_response.status_code == 200
