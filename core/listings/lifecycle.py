"""Listing lifecycle: ageing a listing that crawls stop seeing.

A listing is never deleted because it missed a crawl.  Instead every finished
crawl is swept once (``CrawlJob.swept_at`` records that), every listing it
should have seen but did not is charged one miss, and the status walks
``active -> stale -> delisted`` as the streak grows and back to ``active`` the
moment a crawl sees it again (that reset lives in the persistence layer).

The sweep is deliberately narrow:

* only ``succeeded`` crawls count, and only those that actually persisted
  listings and observed at least one row inside their own scope -- an empty
  crawl says nothing about the source's inventory;
* only listings matching the job's exact place and, when the job specified
  them, its transaction/property are in scope;
* ``hidden`` is a local decision and is never overwritten.

This module touches no network and is never called from the crawl runner: it is
a command, a Celery task and (opt-in) a beat entry.
"""

import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.crawling.enums import CrawlJobStatus
from core.crawling.models import CrawlJob
from core.listings.enums import ListingStatus, PropertyType, TransactionType
from core.listings.models import Listing, ListingStatusEvent

logger = logging.getLogger('north_estate.crawl')

# Statuses the sweep is allowed to move.  ``hidden`` is local and ``delisted``
# is terminal until the listing is seen again.
SWEEPABLE_STATUSES = (ListingStatus.ACTIVE, ListingStatus.STALE)


@dataclass(frozen=True)
class SweepPolicy:
    """How many misses mean what, and how much evidence a crawl must carry."""

    stale_after_misses: int = 1
    delisted_after_misses: int = 3
    min_details: int = 1

    @classmethod
    def from_settings(cls) -> 'SweepPolicy':
        stale = max(1, int(getattr(settings, 'LISTING_STALE_AFTER_MISSES', 1)))
        delisted = max(
            stale, int(getattr(settings, 'LISTING_DELISTED_AFTER_MISSES', 3))
        )
        details = max(1, int(getattr(settings, 'LISTING_SWEEP_MIN_DETAILS', 1)))
        return cls(
            stale_after_misses=stale,
            delisted_after_misses=delisted,
            min_details=details,
        )


@dataclass
class SweepResult:
    jobs_considered: int = 0
    jobs_swept: int = 0
    marked_stale: int = 0
    marked_delisted: int = 0
    skipped: list[dict] = field(default_factory=list)
    dry_run: bool = False

    def as_dict(self) -> dict:
        return {
            'jobs_considered': self.jobs_considered,
            'jobs_swept': self.jobs_swept,
            'marked_stale': self.marked_stale,
            'marked_delisted': self.marked_delisted,
            'skipped': self.skipped,
            'dry_run': self.dry_run,
        }


def sweep_listings(
    *, policy=None, job_id=None, limit=None, dry_run=False, now=None
) -> SweepResult:
    """Charge one miss to every listing an eligible crawl did not see."""
    policy = policy or SweepPolicy.from_settings()
    now = now or timezone.now()
    result = SweepResult(dry_run=dry_run)

    # Materialised so a write during the run can never disturb the iteration.
    for job in list(_eligible_jobs(policy=policy, job_id=job_id, limit=limit)):
        result.jobs_considered += 1
        outcome = _sweep_job(job.pk, policy=policy, dry_run=dry_run, now=now)
        if outcome is None:  # already swept, or claimed by another sweep
            continue
        if outcome['skipped']:
            result.skipped.append(
                {'job_id': job.pk, 'reason': outcome['reason']}
            )
            continue
        result.jobs_swept += 1
        result.marked_stale += outcome['stale']
        result.marked_delisted += outcome['delisted']

    logger.info(
        'listing sweep: considered=%s swept=%s stale=%s delisted=%s skipped=%s',
        result.jobs_considered,
        result.jobs_swept,
        result.marked_stale,
        result.marked_delisted,
        len(result.skipped),
    )
    return result


def _eligible_jobs(*, policy, job_id=None, limit=None):
    jobs = (
        CrawlJob.objects.filter(
            status=CrawlJobStatus.SUCCEEDED,
            swept_at__isnull=True,
            started_at__isnull=False,
            details_fetched__gte=policy.min_details,
        )
        .order_by('started_at', 'id')
    )
    if job_id is not None:
        jobs = jobs.filter(pk=job_id)
    if limit is not None:
        jobs = jobs[: max(0, int(limit))]
    return jobs


def _sweep_job(job_id, *, policy, dry_run, now) -> dict | None:
    """Sweep one job inside its own transaction; ``None`` means "not this time"."""
    with transaction.atomic():
        job = (
            CrawlJob.objects.select_for_update(skip_locked=True)
            .filter(pk=job_id)
            .first()
        )
        if job is None or job.swept_at is not None:
            return None

        scoped = _scoped_listings(job)
        if job.details_fetched == 0:
            return _skip(job, 'crawl persisted no listings', dry_run=dry_run, now=now)
        observed = scoped.filter(last_seen_at__gte=job.started_at).exists()
        if not observed:
            return _skip(
                job,
                'crawl observed no in-scope listings',
                dry_run=dry_run,
                now=now,
            )

        missed = scoped.filter(
            Q(last_seen_at__lt=job.started_at) | Q(last_seen_at__isnull=True)
        )

        if dry_run:
            stale, delisted = _preview(missed, policy=policy)
            return {'skipped': False, 'stale': stale, 'delisted': delisted}

        # The marker is written before the listings so an interrupted sweep is
        # never retried into double-charging the same miss.
        job.swept_at = now
        job.save(update_fields=['swept_at', 'updated_at'])

        stale = delisted = 0
        for listing in missed.select_for_update(skip_locked=True).order_by('id'):
            target = _apply_miss(listing, job=job, policy=policy)
            if target == ListingStatus.STALE:
                stale += 1
            elif target == ListingStatus.DELISTED:
                delisted += 1

        return {'skipped': False, 'stale': stale, 'delisted': delisted}


def _skip(job, reason, *, dry_run, now) -> dict:
    if not dry_run:
        job.swept_at = now
        job.save(update_fields=['swept_at', 'updated_at'])
    logger.warning('listing sweep skipped job %s: %s', job.pk, reason)
    return {'skipped': True, 'reason': reason, 'stale': 0, 'delisted': 0}


def _scoped_listings(job):
    """Listings this crawl was responsible for seeing.

    The job constraint guarantees exactly one place level, so the place filter
    is exact rather than hierarchical: a city-scoped crawl says nothing about a
    listing whose city is unknown.
    """
    listings = Listing.objects.filter(
        source=job.source, status__in=SWEEPABLE_STATUSES
    )
    if job.province_id:
        listings = listings.filter(province_id=job.province_id)
    elif job.city_id:
        listings = listings.filter(city_id=job.city_id)
    elif job.region_id:
        listings = listings.filter(region_id=job.region_id)

    if job.property_type != PropertyType.OTHER:
        listings = listings.filter(property_type=job.property_type)
    if job.transaction_type != TransactionType.UNSPECIFIED:
        listings = listings.filter(transaction_type=job.transaction_type)
    return listings


def _preview(missed, *, policy):
    """Count what a real run would do, without writing anything."""
    stale = delisted = 0
    for misses, status in missed.values_list('consecutive_misses', 'status'):
        target = _target_status(misses + 1, policy)
        if target == status:
            continue
        if target == ListingStatus.STALE:
            stale += 1
        else:
            delisted += 1
    return stale, delisted


def _apply_miss(listing, *, job, policy):
    """Charge one miss to ``listing``; returns the status it ended in."""
    misses = listing.consecutive_misses + 1
    target = _target_status(misses, policy)
    previous = listing.status

    listing.consecutive_misses = misses
    if target != previous:
        listing.status = target
        ListingStatusEvent.objects.create(
            listing=listing,
            from_status=previous,
            to_status=target,
            reason=f'not seen in crawl job #{job.pk}',
        )
    listing.save(update_fields=['consecutive_misses', 'status', 'updated_at'])
    return target


def _target_status(misses, policy):
    if misses >= policy.delisted_after_misses:
        return ListingStatus.DELISTED
    return ListingStatus.STALE
