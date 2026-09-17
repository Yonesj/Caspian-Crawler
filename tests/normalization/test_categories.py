from core.listings.enums import PropertyType, TransactionType
from core.normalization.categories import classify, is_real_estate

DIVAR_PATHS = {
    ('real-estate', 'residential-sell', 'apartment-sell'): (
        TransactionType.SALE,
        PropertyType.APARTMENT,
    ),
    ('real-estate', 'residential-rent', 'apartment-rent'): (
        TransactionType.RENT,
        PropertyType.APARTMENT,
    ),
    ('real-estate', 'commercial-rent', 'shop-rent'): (
        TransactionType.RENT,
        PropertyType.COMMERCIAL,
    ),
    ('real-estate', 'temporary-rent', 'suite-apartment'): (
        TransactionType.RENT,
        PropertyType.APARTMENT,
    ),
    ('real-estate', 'temporary-rent', 'villa'): (
        TransactionType.RENT,
        PropertyType.VILLA,
    ),
}


def test_divar_slugs_carry_both_kinds():
    for path, expected in DIVAR_PATHS.items():
        assert classify(path, '') == expected


def test_sheypoor_slugs_encode_the_transaction():
    assert classify(('real-estate', 'houses-apartments-for-sale'), '') == (
        TransactionType.SALE,
        PropertyType.APARTMENT,
    )
    assert classify(('real-estate', 'house-apartment-for-rent'), '') == (
        TransactionType.RENT,
        PropertyType.APARTMENT,
    )
    assert classify(('real-estate', 'commercial-properties-for-rent'), '') == (
        TransactionType.RENT,
        PropertyType.COMMERCIAL,
    )
    assert classify(('real-estate', 'villa-for-sale'), '') == (
        TransactionType.SALE,
        PropertyType.VILLA,
    )


def test_a_silent_category_falls_back_to_the_title():
    assert classify(('real-estate', 'land'), 'فروش ویلاباغ ۹۵۰ متر') == (
        TransactionType.SALE,
        PropertyType.LAND,
    )
    assert classify(('real-estate', 'land'), 'اجاره زمین زراعی') == (
        TransactionType.RENT,
        PropertyType.LAND,
    )


def test_a_silent_category_and_title_stay_unspecified():
    assert classify(('real-estate', 'land'), 'زمین ۵۰۰ متری') == (
        TransactionType.UNSPECIFIED,
        PropertyType.LAND,
    )


def test_a_price_claim_never_overrides_the_slug():
    # The title mentions "فروش" but the category says rent; the slug wins.
    assert classify(('real-estate', 'apartment-rent'), 'فروش فوری آپارتمان')[0] == (
        TransactionType.RENT
    )


def test_a_title_that_mentions_both_kinds_is_ambiguous():
    assert classify(('real-estate', 'land'), 'فروش یا اجاره')[0] == (
        TransactionType.UNSPECIFIED
    )


def test_unknown_categories_stay_other():
    assert classify(('leisure-hobbies', 'animals', 'farm-animals'), 'فروش گاو') == (
        TransactionType.SALE,
        PropertyType.OTHER,
    )
    assert classify((), '') == (
        TransactionType.UNSPECIFIED,
        PropertyType.OTHER,
    )


def test_real_estate_is_recognised_from_the_source_own_filing():
    assert is_real_estate(('real-estate', 'commercial-rent', 'shop-rent'))
    assert is_real_estate(('real-estate', 'land'))
    assert is_real_estate(('real-estate', 'other-real-estate'))
    assert is_real_estate(('real-estate', 'villa-for-sale'))
    assert not is_real_estate(('leisure-hobbies', 'animals', 'farm-animals'))
    assert not is_real_estate(())
