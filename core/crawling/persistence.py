"""Write normalized listings without ever creating duplicates.

Same-source identity is ``(source, source_id)`` -- the identifier the source
itself uses -- so re-crawling a page updates the existing row instead of
inserting another copy.  This is the M4 guarantee; cross-source duplicate
*candidates* are a later milestone and are deliberately not attempted here.

Two rules keep a partial crawl from destroying data:

* a nullable field the source did not publish this time (an unresolved place, a
  missing timestamp) keeps its previous value rather than being nulled out;
* money is refreshed unconditionally, because "no longer published" and
  "negotiable" are real states that must overwrite a stale amount.
"""

import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.listings.enums import ListingStatus
from core.listings.models import Listing, ListingImage, ListingStatusEvent

logger = logging.getLogger('caspian_crawler.crawl')


@dataclass(frozen=True)
class PersistOutcome:
    created: bool
    reactivated: bool


def upsert_listing(
    normalized,
    *,
    raw: dict | None = None,
    image_urls=(),
    seen_at=None,
) -> PersistOutcome:
    """Create or refresh the row for ``normalized`` and return what happened."""
    seen_at = seen_at or timezone.now()
    try:
        return _upsert(normalized, raw=raw, image_urls=image_urls, seen_at=seen_at)
    except IntegrityError:
        # Another worker inserted the same identity between our SELECT and
        # INSERT.  Re-running the upsert now finds the row and updates it.
        logger.warning(
            'concurrent insert for %s:%s; retrying upsert',
            normalized.source,
            normalized.source_id,
        )
        return _upsert(normalized, raw=raw, image_urls=image_urls, seen_at=seen_at)


def _upsert(normalized, *, raw, image_urls, seen_at) -> PersistOutcome:
    identity = {'source': normalized.source, 'source_id': normalized.source_id}
    with transaction.atomic():
        listing = Listing.objects.select_for_update().filter(**identity).first()
        created = listing is None
        if created:
            listing = Listing(**identity)

        previous_status = None if created else listing.status
        _apply_fields(listing, normalized, raw=raw, seen_at=seen_at, created=created)
        listing.save()

        if image_urls:
            _replace_images(listing, image_urls)

        if created:
            return PersistOutcome(created=True, reactivated=False)

        reactivated = previous_status in {ListingStatus.STALE, ListingStatus.DELISTED}
        if reactivated:
            # Availability is modelled, not deleted: a listing that reappears is
            # flipped back to active and the transition is logged.
            ListingStatusEvent.objects.create(
                listing=listing,
                from_status=previous_status,
                to_status=ListingStatus.ACTIVE,
                reason='seen again in a crawl',
            )

        return PersistOutcome(created=False, reactivated=reactivated)


def _apply_fields(listing, normalized, *, raw, seen_at, created) -> None:
    listing.source_url = normalized.source_url
    listing.title = normalized.title
    listing.description = normalized.description
    listing.transaction_type = normalized.transaction_type
    listing.property_type = normalized.property_type
    listing.last_seen_at = seen_at
    listing.last_checked_at = seen_at
    listing.raw_data = dict(raw) if raw else listing.raw_data

    if normalized.raw_location:
        listing.raw_location = normalized.raw_location

    # A place that could not be resolved this run must not erase a place that
    # was resolved before (a missing alias is our gap, not the source's data).
    if normalized.province_id is not None:
        listing.province_id = normalized.province_id
    if normalized.city_id is not None:
        listing.city_id = normalized.city_id
    if normalized.region_id is not None:
        listing.region_id = normalized.region_id

    # Money and physical attributes describe the listing's *current* state, so
    # they are refreshed even when the new value is None.
    listing.sale_price = normalized.sale_price
    listing.deposit = normalized.deposit
    listing.monthly_rent = normalized.monthly_rent
    listing.price_currency = normalized.price_currency
    listing.is_price_negotiable = normalized.is_price_negotiable
    listing.area_sqm = normalized.area_sqm
    listing.rooms = normalized.rooms

    if normalized.published_at is not None:
        listing.published_at = normalized.published_at

    # The crawl saw it, so the miss streak is broken -- whether it was still
    # active or is being brought back from stale/delisted.
    listing.consecutive_misses = 0

    if created:
        listing.status = ListingStatus.ACTIVE
    elif listing.status in {ListingStatus.STALE, ListingStatus.DELISTED}:
        listing.status = ListingStatus.ACTIVE


def _replace_images(listing, image_urls) -> None:
    unique = list(dict.fromkeys(url for url in image_urls if url))
    ListingImage.objects.filter(listing=listing).delete()
    ListingImage.objects.bulk_create(
        ListingImage(listing=listing, url=url, position=position)
        for position, url in enumerate(unique)
    )
