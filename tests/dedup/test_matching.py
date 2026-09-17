"""The duplicate matcher is pure: no database, no network, no clock."""

from datetime import timedelta

from django.utils import timezone

from core.dedup.matching import (
    DedupPolicy,
    ListingFingerprint,
    blockers,
    match_pair,
    signals,
    title_tokens,
)
from core.listings.enums import ListingStatus, PropertyType, TransactionType

PUBLISHED = timezone.datetime(2026, 9, 1, 12, 0, tzinfo=timezone.UTC)


def fingerprint(**overrides):
    values = {
        'listing_id': 1,
        'source': 'divar',
        'transaction_type': TransactionType.SALE,
        'property_type': PropertyType.APARTMENT,
        'province_id': 1,
        'city_id': 2,
        'title': 'آپارتمان ۱۰۰ متری',
        'area_sqm': 100.0,
        'price': 3_000_000_000.0,
        'published_at': PUBLISHED,
    }
    values.update(overrides)
    return ListingFingerprint(**values)


def twin(**overrides):
    values = {'listing_id': 2, 'source': 'sheypoor', 'title': 'آپارتمان 100 متری'}
    values.update(overrides)
    return fingerprint(**values)


def names(*args, **kwargs):
    return [signal.name for signal in signals(*args, **kwargs)]


def test_two_listings_that_agree_on_everything_match():
    match = match_pair(fingerprint(), twin())

    assert match is not None
    assert match.score == 100
    assert [signal.name for signal in match.signals] == [
        'area',
        'price',
        'title',
        'published',
    ]


def test_a_similar_listing_scores_below_the_threshold():
    match = match_pair(
        fingerprint(),
        twin(area_sqm=140.0, price=3_400_000_000.0, title='ویلای جنگلی دوخوابه'),
    )

    assert match is None


def test_area_tolerance_is_the_larger_of_three_square_metres_and_five_percent():
    policy = DedupPolicy()

    # 5% of 100 is 5, so 4 sqm off still matches but 6 does not.
    within = match_pair(fingerprint(), twin(area_sqm=104.0))
    assert within is not None
    assert 'area' in names(fingerprint(), twin(area_sqm=104.0))

    bare = dict(title='', price=None, published_at=None)
    assert match_pair(fingerprint(**bare), twin(area_sqm=106.0, **bare)) is None
    assert policy.area_tolerance_sqm == 3.0


def test_price_must_be_within_five_percent():
    assert 'price' in names(fingerprint(area_sqm=None), twin(area_sqm=None))
    assert 'price' not in names(
        fingerprint(area_sqm=None), twin(area_sqm=None, price=3_300_000_000.0)
    )


def test_a_missing_price_contributes_no_signal_instead_of_a_free_match():
    match = match_pair(fingerprint(price=None), twin(price=None))

    assert match is not None
    assert 'price' not in [signal.name for signal in match.signals]


def test_publication_window_is_three_days():
    bare = {'area_sqm': None, 'price': None, 'title': 'دفتر کار اداری'}

    assert 'published' in names(
        fingerprint(**bare), twin(**bare, published_at=PUBLISHED + timedelta(days=3))
    )
    assert 'published' not in names(
        fingerprint(**bare), twin(**bare, published_at=PUBLISHED + timedelta(days=10))
    )


def test_one_signal_is_never_enough():
    match = match_pair(
        fingerprint(price=None, published_at=None, title='آپارتمان نوساز'),
        twin(price=None, published_at=None, title='دفتر کار اداری'),
    )

    assert match is None  # identical area alone scores 40 < 50


def test_transaction_property_city_and_source_are_blockers():
    base = fingerprint()

    assert blockers(base, twin(transaction_type=TransactionType.RENT)) == [
        'transaction_mismatch'
    ]
    assert blockers(base, twin(property_type=PropertyType.LAND)) == ['property_mismatch']
    assert blockers(base, twin(city_id=99)) == ['city_mismatch']
    assert blockers(base, twin(province_id=99)) == ['province_mismatch']
    assert blockers(base, fingerprint(listing_id=3)) == ['same_source']

    assert match_pair(fingerprint(), fingerprint(listing_id=3)) is None


def test_unspecified_property_and_transaction_do_not_block():
    base = fingerprint(
        property_type=PropertyType.OTHER, transaction_type=TransactionType.UNSPECIFIED
    )

    assert blockers(base, twin(property_type=PropertyType.APARTMENT)) == []
    assert blockers(base, twin(transaction_type=TransactionType.RENT)) == []


def test_hidden_listings_and_already_linked_rows_are_blocked():
    assert blockers(fingerprint(status=ListingStatus.HIDDEN), twin()) == ['not_available']
    assert blockers(fingerprint(duplicate_of_id=7), twin()) == ['already_linked']


def test_titles_are_folded_before_comparison():
    left = title_tokens('آپارتمان ۱۰۰ متری در ساری')
    right = title_tokens('آپارتمان 100 متری، ساری')

    assert left == right
    assert 'در' not in left  # a stopword carries no evidence


def test_a_different_area_in_the_title_is_visible_to_the_matcher():
    left = title_tokens('آپارتمان ۱۰۰ متری')
    right = title_tokens('آپارتمان ۱۲۰ متری')

    assert left - right == {'100'}
    assert left & right == {'آپارتمان', 'متری'}
