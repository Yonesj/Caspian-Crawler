"""Detect duplicate candidates and record a reviewer's decision.

Detection is a bounded, deterministic batch job: listings are bucketed by
``(transaction, city)`` and only the most recently seen
``DEDUP_MAX_LISTINGS_PER_BUCKET`` rows of each bucket are compared pairwise, so
one run stays close to linear in the number of listings we hold.  It never
touches the network and never runs inside the crawl pipeline.

Confirmation is deliberately timid.  It sets ``Listing.duplicate_of`` on the
listing the reviewer chose to discard and stops there: no fields are copied, no
row is hidden, and no row is ever deleted.
"""

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.listings.models import Listing

from .enums import DuplicateCanonical, DuplicateStatus
from .matching import (
    COMPARABLE_STATUSES,
    DedupPolicy,
    ListingFingerprint,
    match_pair,
)
from .models import DuplicateCandidate

logger = logging.getLogger('caspian_crawler.crawl')

# A reviewer's verdict is data, not a cache: re-detection refreshes the score
# and the signals but never rewrites these.
HUMAN_DECISIONS = (DuplicateStatus.CONFIRMED, DuplicateStatus.REJECTED)


@dataclass
class DetectResult:
    buckets: int = 0
    listings: int = 0
    pairs_evaluated: int = 0
    matches: int = 0
    candidates_created: int = 0
    candidates_updated: int = 0
    dry_run: bool = False

    def as_dict(self) -> dict:
        return {
            'buckets': self.buckets,
            'listings': self.listings,
            'pairs_evaluated': self.pairs_evaluated,
            'matches': self.matches,
            'candidates_created': self.candidates_created,
            'candidates_updated': self.candidates_updated,
            'dry_run': self.dry_run,
        }


def detect_candidates(
    *, policy=None, source=None, city=None, limit=None, dry_run=False
) -> DetectResult:
    """Record a pending candidate for every cross-source pair that matches."""
    policy = policy or DedupPolicy()
    limit = limit or int(getattr(settings, 'DEDUP_MAX_LISTINGS_PER_BUCKET', 500))
    result = DetectResult(dry_run=dry_run)

    for _key, bucket in _buckets(_candidate_listings(source=source, city=city), limit=limit):
        result.buckets += 1
        result.listings += len(bucket)
        for index, left in enumerate(bucket):
            for right in bucket[index + 1:]:
                result.pairs_evaluated += 1
                match = match_pair(left, right, policy)
                if match is None:
                    continue
                result.matches += 1
                action = _record(left, right, match, dry_run=dry_run)
                if action == 'created':
                    result.candidates_created += 1
                else:
                    result.candidates_updated += 1

    logger.info(
        'duplicate detection: buckets=%s listings=%s pairs=%s matches=%s '
        'created=%s updated=%s',
        result.buckets,
        result.listings,
        result.pairs_evaluated,
        result.matches,
        result.candidates_created,
        result.candidates_updated,
    )
    return result


def fingerprint(listing) -> ListingFingerprint:
    """The pure value the matcher sees, built from a listing instance."""
    return ListingFingerprint(
        listing_id=listing.pk,
        source=listing.source,
        transaction_type=listing.transaction_type,
        property_type=listing.property_type,
        province_id=listing.province_id,
        city_id=listing.city_id,
        title=listing.title,
        area_sqm=None if listing.area_sqm is None else float(listing.area_sqm),
        price=_headline_price(listing),
        published_at=listing.published_at,
        status=listing.status,
        duplicate_of_id=listing.duplicate_of_id,
    )


@transaction.atomic
def confirm_candidate(candidate, *, canonical, reviewed_by=None, note=''):
    """Record that the pair really is one listing, keeping ``canonical``."""
    if canonical not in DuplicateCanonical.values:
        raise ValueError(f'canonical must be one of {DuplicateCanonical.values}.')
    candidate = DuplicateCandidate.objects.select_for_update().get(pk=candidate.pk)
    winner_id, loser_id = _sides(candidate, canonical)

    loser = Listing.objects.select_for_update().get(pk=loser_id)
    if loser.duplicate_of_id not in (None, winner_id):
        # Last review wins, but never silently.
        logger.warning(
            'listing %s was linked to %s; repointing it to %s',
            loser_id,
            loser.duplicate_of_id,
            winner_id,
        )
    loser.duplicate_of_id = winner_id
    loser.save(update_fields=['duplicate_of', 'updated_at'])

    candidate.status = DuplicateStatus.CONFIRMED
    candidate.canonical = canonical
    _stamp_review(candidate, reviewed_by=reviewed_by, note=note)
    return candidate


@transaction.atomic
def reject_candidate(candidate, *, reviewed_by=None, note=''):
    """Record that the pair is *not* one listing and drop any link it created."""
    candidate = DuplicateCandidate.objects.select_for_update().get(pk=candidate.pk)
    if candidate.status == DuplicateStatus.CONFIRMED and candidate.canonical:
        winner_id, loser_id = _sides(candidate, candidate.canonical)
        Listing.objects.filter(pk=loser_id, duplicate_of_id=winner_id).update(
            duplicate_of=None, updated_at=timezone.now()
        )

    candidate.status = DuplicateStatus.REJECTED
    candidate.canonical = None
    _stamp_review(candidate, reviewed_by=reviewed_by, note=note)
    return candidate


# -- internals ----------------------------------------------------------------

def _sides(candidate, canonical):
    if canonical == DuplicateCanonical.LEFT:
        return candidate.left_id, candidate.right_id
    return candidate.right_id, candidate.left_id


def _stamp_review(candidate, *, reviewed_by, note):
    candidate.reviewed_by = reviewed_by
    candidate.reviewed_at = timezone.now()
    if note:
        candidate.note = note[:500]
    candidate.save(
        update_fields=[
            'status', 'canonical', 'reviewed_by', 'reviewed_at', 'note', 'updated_at',
        ]
    )


def _candidate_listings(*, source=None, city=None):
    """Listings worth comparing, most recently seen first within each bucket."""
    listings = Listing.objects.filter(
        status__in=COMPARABLE_STATUSES,
        duplicate_of__isnull=True,
        city__isnull=False,
    ).order_by('-last_seen_at', '-id')
    if source:
        listings = listings.filter(source=source)
    if city:
        listings = listings.filter(city=city)
    return listings


def _buckets(listings, *, limit):
    """Group by ``(transaction, city)`` and keep the newest ``limit`` rows."""
    grouped: dict[tuple, list[ListingFingerprint]] = {}
    for listing in listings:
        item = fingerprint(listing)
        grouped.setdefault((item.transaction_type, item.city_id), []).append(item)
    for key, bucket in grouped.items():
        yield key, bucket[: max(0, limit)]


def _record(left, right, match, *, dry_run) -> str:
    """Upsert the candidate, preserving any human verdict already on it."""
    lower_id, higher_id = sorted((left.listing_id, right.listing_id))
    defaults = {'score': match.score, 'signals': match.as_dict()['signals']}
    existing = DuplicateCandidate.objects.filter(
        left_id=lower_id, right_id=higher_id
    ).first()

    if dry_run:
        return 'updated' if existing is not None else 'created'

    if existing is None:
        try:
            DuplicateCandidate.objects.create(
                left_id=lower_id, right_id=higher_id, **defaults
            )
        except IntegrityError:
            # Another detector inserted the same pair in the meantime; refresh it.
            _refresh(lower_id, higher_id, defaults)
            return 'updated'
        return 'created'

    _refresh(lower_id, higher_id, defaults)
    return 'updated'


def _refresh(lower_id, higher_id, defaults) -> None:
    DuplicateCandidate.objects.filter(
        left_id=lower_id, right_id=higher_id
    ).update(
        score=defaults['score'],
        signals=defaults['signals'],
        updated_at=timezone.now(),
    )


def _headline_price(listing):
    """The amount a buyer compares first: sale price, else deposit, else rent."""
    for value in (listing.sale_price, listing.deposit, listing.monthly_rent):
        if value is not None:
            return float(value)
    return None
