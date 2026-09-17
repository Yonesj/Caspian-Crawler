"""The source-independent shape a crawl hands to persistence.

A :class:`NormalizedListing` is deliberately a plain frozen dataclass rather
than a model instance: normalization must be testable without a database, and
the pipeline (not the normalizer) decides when a row is written.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.listings.enums import Currency, PropertyType, TransactionType


@dataclass(frozen=True)
class NormalizedListing:
    source: str
    source_id: str
    source_url: str
    title: str
    description: str = ''
    transaction_type: str = TransactionType.UNSPECIFIED
    property_type: str = PropertyType.OTHER
    province_id: int | None = None
    city_id: int | None = None
    region_id: int | None = None
    raw_location: str = ''
    sale_price: Decimal | None = None
    deposit: Decimal | None = None
    monthly_rent: Decimal | None = None
    # The unit the stored amounts are in, not the unit the source printed: a
    # Rial price is converted to Toman and its wording kept in ``raw_data``.
    price_currency: str = Currency.TOMAN
    is_price_negotiable: bool = False
    area_sqm: Decimal | None = None
    rooms: int | None = None
    published_at: datetime | None = None
    category_path: tuple[str, ...] = ()
    is_real_estate: bool = False
