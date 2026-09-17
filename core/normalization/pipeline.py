"""Adapters' DTOs in, normalized listings out.

The entry points are total: every field a source did not publish (or published
in a form we cannot read) narrows the result instead of raising, so one odd
listing can never abort a crawl.  Only the adapter layer rejects payloads it
cannot parse at all.
"""

import logging

from core.listings.enums import Currency, TransactionType

from .attributes import (
    AREA_KEY_SET,
    DEPOSIT_KEY_SET,
    RENT_KEY_SET,
    ROOMS_KEY_SET,
    SALE_KEY_SET,
    first_value,
    fold_attributes,
    parse_area,
    parse_rooms,
    price_from_attributes,
)
from .categories import classify, is_real_estate
from .dates import parse_published_at
from .dto import NormalizedListing
from .locations import LocationIndex
from .money import DEPOSIT, RENT, SALE, PriceValue, field_hint, parse_price
from .text import clean_display

logger = logging.getLogger('north_estate.normalize')

DEFAULT_FIELD = {
    TransactionType.SALE: SALE,
    TransactionType.RENT: RENT,
}


def normalize_detail(detail, *, index: LocationIndex) -> NormalizedListing:
    """Normalize one listing's detail page."""
    transaction_type, property_type = classify(detail.category_path, detail.title)
    attributes = fold_attributes(detail.attributes)
    sale, deposit, rent, negotiable = _money(
        attributes, detail.raw_price, transaction_type
    )
    match = index.resolve(
        raw_location=detail.raw_location, place_refs=detail.place_refs, source=detail.source
    )
    return NormalizedListing(
        source=str(detail.source),
        source_id=str(detail.source_id),
        source_url=detail.url,
        title=clean_display(detail.title),
        description=clean_display(detail.description),
        transaction_type=transaction_type,
        property_type=property_type,
        province_id=match.province_id,
        city_id=match.city_id,
        region_id=match.region_id,
        raw_location=clean_display(detail.raw_location),
        sale_price=sale.amount_toman,
        deposit=deposit.amount_toman,
        monthly_rent=rent.amount_toman,
        price_currency=Currency.TOMAN,
        is_price_negotiable=negotiable,
        area_sqm=parse_area(first_value(attributes, AREA_KEY_SET)),
        rooms=parse_rooms(first_value(attributes, ROOMS_KEY_SET)),
        published_at=parse_published_at(detail.published_at_text),
        category_path=tuple(detail.category_path or ()),
        is_real_estate=is_real_estate(detail.category_path),
    )


def normalize_stub(stub, *, index: LocationIndex) -> NormalizedListing:
    """Normalize a list-page row: identity, price and place, nothing more.

    List pages do not publish the category or the attribute block, so the
    classification stays unspecified until the detail page is fetched; the price
    is read from the row's own label when it carries one ("اجاره: ...").
    """
    transaction_type, property_type = classify(stub.category_path, stub.title)
    sale, deposit, rent, negotiable = _money({}, stub.raw_price, transaction_type)
    match = index.resolve(
        raw_location=stub.raw_location, place_refs=stub.place_refs, source=stub.source
    )
    return NormalizedListing(
        source=str(stub.source),
        source_id=str(stub.source_id),
        source_url=stub.url,
        title=clean_display(stub.title),
        transaction_type=transaction_type,
        property_type=property_type,
        province_id=match.province_id,
        city_id=match.city_id,
        region_id=match.region_id,
        raw_location=clean_display(stub.raw_location),
        sale_price=sale.amount_toman,
        deposit=deposit.amount_toman,
        monthly_rent=rent.amount_toman,
        price_currency=Currency.TOMAN,
        is_price_negotiable=negotiable,
        category_path=tuple(stub.category_path or ()),
        is_real_estate=is_real_estate(stub.category_path),
    )


def _money(folded, raw_price, transaction_type):
    """Resolve the three money fields plus the negotiable flag."""
    fields = {
        SALE: price_from_attributes(folded, SALE_KEY_SET) if folded else PriceValue(),
        DEPOSIT: price_from_attributes(folded, DEPOSIT_KEY_SET) if folded else PriceValue(),
        RENT: price_from_attributes(folded, RENT_KEY_SET) if folded else PriceValue(),
    }
    negotiable = any(value.is_negotiable for value in fields.values())

    if raw_price and all(value.is_missing for value in fields.values()):
        value = parse_price(raw_price)
        if value.is_negotiable:
            negotiable = True
        elif value.amount_toman is not None:
            target = field_hint(raw_price) or DEFAULT_FIELD.get(transaction_type)
            if target is None:
                logger.warning(
                    'price has no field to belong to (%s): %r', transaction_type, raw_price
                )
            else:
                fields[target] = value

    return fields[SALE], fields[DEPOSIT], fields[RENT], negotiable
