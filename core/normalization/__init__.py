"""Source-shaped DTOs to the normalized listing representation.

Pure conversion: no database writes, no network, no source payloads read here.
"""

from .categories import classify, is_real_estate
from .dates import parse_published_at
from .dto import NormalizedListing
from .locations import LocationIndex, LocationMatch
from .money import PriceValue, parse_price
from .pipeline import normalize_detail, normalize_stub

__all__ = [
    'LocationIndex',
    'LocationMatch',
    'NormalizedListing',
    'PriceValue',
    'classify',
    'is_real_estate',
    'normalize_detail',
    'normalize_stub',
    'parse_price',
    'parse_published_at',
]
