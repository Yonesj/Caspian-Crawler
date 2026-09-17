from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from core.listings.enums import Currency, ListingStatus, PropertyType, TransactionType
from core.listings.models import Listing, ListingImage, ListingStatusEvent
from core.locations.models import City, Province
from core.sources.enums import Source

pytestmark = pytest.mark.integration


def make_listing(**overrides):
    fields = {
        'source': Source.DIVAR,
        'source_id': 'abc123',
        'source_url': 'https://divar.ir/v/abc123',
        'title': 'آپارتمان ۱۰۰ متری',
        'transaction_type': TransactionType.SALE,
        'property_type': PropertyType.APARTMENT,
    }
    fields.update(overrides)
    return Listing.objects.create(**fields)


def test_listing_defaults_are_conservative(db):
    listing = make_listing()

    assert listing.status == ListingStatus.ACTIVE
    assert listing.is_available is True
    assert listing.price_currency == Currency.TOMAN
    # "Not specified" is null, never 0.
    assert listing.sale_price is None
    assert listing.deposit is None
    assert listing.monthly_rent is None
    assert listing.is_price_negotiable is False
    assert listing.raw_data == {}


def test_source_identifier_is_the_listing_identity(db):
    make_listing(source_id='same-id', source_url='https://divar.ir/v/first')

    # A changed URL must not create a second row for the same source listing.
    with pytest.raises(IntegrityError), transaction.atomic():
        make_listing(source_id='same-id', source_url='https://divar.ir/v/second')

    # The same external id on a different source is a different listing.
    make_listing(source=Source.SHEYPOOR, source_id='same-id')


def test_negative_amounts_are_rejected_by_the_database(db):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_listing(sale_price=Decimal('-1'))

    with pytest.raises(IntegrityError), transaction.atomic():
        make_listing(area_sqm=Decimal('-0.5'))


def test_listing_location_is_optional_and_resolved_when_present(db):
    province = Province.objects.create(
        code='gilan', name_fa='گیلان', name_en='Gilan'
    )
    city = City.objects.create(
        province=province, code='rasht', name_fa='رشت', name_en='Rasht'
    )

    unresolved = make_listing(source_id='unresolved', raw_location='رشت، گلسار')
    assert unresolved.location_target is None
    assert unresolved.raw_location == 'رشت، گلسار'

    resolved = make_listing(source_id='resolved', city=city)
    assert resolved.location_target == city


def test_images_keep_their_order_and_position_is_unique_per_listing(db):
    listing = make_listing()
    second = ListingImage.objects.create(
        listing=listing, url='https://cdn.example.com/2.jpg', position=1
    )
    first = ListingImage.objects.create(
        listing=listing, url='https://cdn.example.com/1.jpg', position=0
    )

    assert list(listing.images.all()) == [first, second]

    with pytest.raises(IntegrityError), transaction.atomic():
        ListingImage.objects.create(
            listing=listing, url='https://cdn.example.com/dup.jpg', position=0
        )


def test_status_history_is_appended_and_cascades_with_the_listing(db):
    listing = make_listing()
    ListingStatusEvent.objects.create(
        listing=listing, from_status=ListingStatus.ACTIVE, to_status=ListingStatus.DELISTED,
        reason='missing from crawl',
    )
    ListingStatusEvent.objects.create(
        listing=listing, from_status=ListingStatus.DELISTED, to_status=ListingStatus.ACTIVE,
        reason='reappeared',
    )

    events = list(listing.status_events.all())
    assert [event.to_status for event in events] == [
        ListingStatus.ACTIVE, ListingStatus.DELISTED,
    ]
    assert events[0].reason == 'reappeared'

    listing.delete()
    assert ListingStatusEvent.objects.count() == 0
