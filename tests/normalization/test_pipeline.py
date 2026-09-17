import logging
from datetime import UTC, datetime
from decimal import Decimal

from core.listings.enums import Currency, PropertyType, TransactionType
from core.normalization import normalize_detail, normalize_stub
from core.sources.adapters import divar, sheypoor
from core.sources.dto import CrawlScope, ListingDetail
from tests.sources.conftest import fixture_json, fixture_text


def divar_stubs():
    payload = fixture_json('divar_list_page1.json')
    return divar.parse_list_page(payload, CrawlScope('22'), 1).items


def sheypoor_stubs():
    html = fixture_text('sheypoor_list_page1.html')
    return sheypoor.parse_list_page(html, CrawlScope('mazandaran'), 1).items


def test_a_divar_sale_detail_is_fully_normalized(index, divar_sale_detail):
    listing = normalize_detail(divar_sale_detail, index=index)

    assert listing.source == 'divar'
    assert listing.source_url.startswith('https://divar.ir/v/')
    assert listing.transaction_type == TransactionType.SALE
    assert listing.property_type == PropertyType.APARTMENT
    assert listing.sale_price == 6950000000
    assert listing.deposit is None and listing.monthly_rent is None
    assert not listing.is_price_negotiable
    assert listing.price_currency == Currency.TOMAN
    assert listing.area_sqm == Decimal('136.00')
    assert listing.rooms == 3
    assert listing.published_at == datetime(2026, 9, 17, 9, 13, tzinfo=UTC)
    assert (listing.province_id, listing.city_id) == (1, 22)
    assert listing.is_real_estate


def test_a_divar_rent_detail_fills_deposit_and_rent(index, divar_rent_detail):
    listing = normalize_detail(divar_rent_detail, index=index)

    assert listing.transaction_type == TransactionType.RENT
    assert listing.property_type == PropertyType.APARTMENT
    assert listing.deposit == 100000000
    assert listing.monthly_rent == 10000000
    assert listing.sale_price is None
    assert listing.rooms == 1


def test_the_rent_fixture_with_a_shop_category(index):
    detail = divar.parse_detail(
        fixture_json('divar_detail_gasGkf8r.json'), 'gasGkf8r'
    )

    listing = normalize_detail(detail, index=index)

    assert listing.property_type == PropertyType.COMMERCIAL
    assert listing.transaction_type == TransactionType.RENT
    assert listing.deposit == 30000000
    assert listing.monthly_rent == 60000000


def test_a_negotiable_sheypoor_detail_keeps_its_flag_and_no_amount(index, sheypoor_detail):
    listing = normalize_detail(sheypoor_detail, index=index)

    assert listing.is_price_negotiable
    assert listing.sale_price is None
    assert listing.deposit is None and listing.monthly_rent is None
    # The category is a bare "land"; the title is what says it is for sale.
    assert listing.transaction_type == TransactionType.SALE
    assert listing.property_type == PropertyType.LAND
    assert listing.area_sqm == Decimal('950.00')
    assert listing.is_real_estate
    # Resolved from Sheypoor's neighbourhood slug, not from the text.
    assert (listing.province_id, listing.city_id, listing.region_id) == (1, 23, 31)


def test_a_stub_price_is_read_from_its_own_label(index):
    stub = next(item for item in divar_stubs() if item.source_id == 'gasGkf8r')

    listing = normalize_stub(stub, index=index)

    assert stub.raw_price == 'اجاره: ۶۰,۰۰۰,۰۰۰ تومان'
    assert listing.monthly_rent == 60000000
    assert listing.transaction_type == TransactionType.RENT
    assert listing.city_id == 22


def test_a_negotiable_stub_is_flagged(index):
    stub = next(item for item in sheypoor_stubs() if item.source_id == '464398666')

    listing = normalize_stub(stub, index=index)

    assert listing.is_price_negotiable
    assert listing.sale_price is None
    assert listing.transaction_type == TransactionType.SALE


def test_an_unlabelled_stub_price_is_left_unplaced(index, caplog):
    stub = next(item for item in divar_stubs() if item.source_id == 'gapqVBMq')

    with caplog.at_level(logging.WARNING, logger='north_estate.normalize'):
        listing = normalize_stub(stub, index=index)

    # Nothing in the row says whether this is a total price or a monthly rent,
    # and the category is only known from the detail page, so no amount is
    # invented and the raw text stays in raw_data upstream.
    assert listing.sale_price is None
    assert listing.monthly_rent is None
    assert listing.transaction_type == TransactionType.UNSPECIFIED
    assert 'no field to belong to' in caplog.text


def test_normalization_narrows_instead_of_raising(index):
    # A detail page with nothing usable in it must still produce a listing
    # rather than an exception: the pipeline decides what to keep.
    empty = ListingDetail(
        source='divar', source_id='x', url='https://divar.ir/v/x', title=''
    )

    listing = normalize_detail(empty, index=index)

    assert listing.transaction_type == TransactionType.UNSPECIFIED
    assert listing.property_type == PropertyType.OTHER
    assert listing.sale_price is None and listing.published_at is None
    assert listing.city_id is None
    assert not listing.is_real_estate
    assert listing.source_id == 'x'
