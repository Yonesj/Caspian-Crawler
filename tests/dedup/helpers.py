"""Builders for pairs of listings on two sources."""

from django.utils import timezone

from core.sources.enums import Source
from tests.listings.helpers import T0, make_listing

PUBLISHED = timezone.datetime(2026, 9, 1, 10, 0, tzinfo=timezone.UTC)

# What a sale apartment looks like when two sources describe the same one.
SHARED = {
    'transaction_type': 'sale',
    'property_type': 'apartment',
    'area_sqm': 100,
    'sale_price': 3_000_000_000,
    'published_at': PUBLISHED,
    'last_seen_at': T0,
}


def matching_pair(places, *, city=None, **overrides):
    """Two listings on different sources that describe the same property."""
    values = dict(SHARED)
    values.update(overrides)
    values.setdefault('city', city or places.city)
    left = make_listing(
        places,
        source_id=f'divar-{values["city"].pk}',
        source=Source.DIVAR,
        title='آپارتمان ۱۰۰ متری در ساری',
        **values,
    )
    right = make_listing(
        places,
        source_id=f'sheypoor-{values["city"].pk}',
        source=Source.SHEYPOOR,
        title='آپارتمان 100 متری، ساری',
        **values,
    )
    return left, right
