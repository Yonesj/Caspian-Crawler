from datetime import UTC, datetime, timedelta

import pytest

from core.crawling.persistence import upsert_listing
from core.listings.enums import ListingStatus, PropertyType, TransactionType
from core.listings.models import Listing, ListingImage, ListingStatusEvent
from core.normalization.dto import NormalizedListing

pytestmark = pytest.mark.integration


def normalized(**overrides):
    values = {
        'source': 'divar',
        'source_id': 'abc123',
        'source_url': 'https://divar.ir/v/abc123',
        'title': 'آپارتمان ۱۰۰ متری',
        'transaction_type': TransactionType.SALE,
        'property_type': PropertyType.APARTMENT,
        'sale_price': 3_000_000_000,
        'area_sqm': 100,
    }
    values.update(overrides)
    return NormalizedListing(**values)


def test_first_write_creates_a_listing(db):
    outcome = upsert_listing(normalized(), raw={'id': 'abc123'})

    assert outcome.created is True
    listing = Listing.objects.get(source='divar', source_id='abc123')
    assert listing.title == 'آپارتمان ۱۰۰ متری'
    assert listing.sale_price == 3_000_000_000
    assert listing.last_seen_at is not None


def test_re_crawling_updates_instead_of_duplicating(db):
    first_seen = datetime(2026, 9, 1, tzinfo=UTC)
    upsert_listing(normalized(), raw={'v': 1}, seen_at=first_seen)
    first_message = Listing.objects.get().first_seen_at
    later = first_seen + timedelta(days=1)

    outcome = upsert_listing(
        normalized(title='آپارتمان نوساز ۱۲۰ متری', sale_price=3_500_000_000),
        raw={'v': 2},
        seen_at=later,
    )

    assert outcome.created is False
    assert Listing.objects.count() == 1
    listing = Listing.objects.get()
    assert listing.title == 'آپارتمان نوساز ۱۲۰ متری'
    assert listing.sale_price == 3_500_000_000
    assert listing.last_seen_at == later
    assert listing.raw_data == {'v': 2}
    assert listing.first_seen_at == first_message


def test_money_is_refreshed_even_when_the_source_stops_publishing_it(db):
    upsert_listing(normalized(), raw={})

    upsert_listing(
        normalized(sale_price=None, is_price_negotiable=True), raw={}
    )

    listing = Listing.objects.get()
    assert listing.sale_price is None
    assert listing.is_price_negotiable is True


def test_an_unresolved_place_does_not_erase_a_known_one(db, places):
    upsert_listing(normalized(province_id=places.province.pk, city_id=places.city.pk), raw={})

    upsert_listing(normalized(province_id=None, city_id=None), raw={})

    listing = Listing.objects.get()
    assert listing.city_id == places.city.pk


def test_images_are_replaced_without_duplicates(db):
    upsert_listing(
        normalized(), raw={}, image_urls=['https://img/1.jpg', 'https://img/2.jpg']
    )
    upsert_listing(normalized(), raw={}, image_urls=['https://img/3.jpg'])

    images = list(ListingImage.objects.filter(listing__source_id='abc123'))
    assert [image.url for image in images] == ['https://img/3.jpg']
    assert images[0].position == 0


def test_empty_image_list_keeps_the_existing_images(db):
    upsert_listing(normalized(), raw={}, image_urls=['https://img/1.jpg'])
    upsert_listing(normalized(), raw={}, image_urls=[])

    assert ListingImage.objects.count() == 1


def test_a_listing_that_reappears_is_reactivated_and_logged(db):
    upsert_listing(normalized(), raw={})
    Listing.objects.update(status=ListingStatus.DELISTED)

    outcome = upsert_listing(normalized(), raw={})

    listing = Listing.objects.get()
    assert outcome.reactivated is True
    assert listing.status == ListingStatus.ACTIVE
    event = ListingStatusEvent.objects.get(listing=listing)
    assert event.from_status == ListingStatus.DELISTED
    assert event.to_status == ListingStatus.ACTIVE


def test_a_different_source_id_is_a_different_listing(db):
    upsert_listing(normalized(), raw={})
    upsert_listing(normalized(source_id='def456'), raw={})

    assert Listing.objects.count() == 2


def test_a_hidden_listing_stays_hidden(db):
    upsert_listing(normalized(), raw={})
    Listing.objects.update(status=ListingStatus.HIDDEN)

    upsert_listing(normalized(), raw={})

    assert Listing.objects.get().status == ListingStatus.HIDDEN
