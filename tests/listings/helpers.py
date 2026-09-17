"""Crawl-job and listing builders shared by the lifecycle test modules."""

from datetime import timedelta

from django.utils import timezone

from core.crawling.enums import CrawlJobStatus
from core.listings.enums import PropertyType, TransactionType
from core.listings.models import Listing
from core.sources.enums import Source

T0 = timezone.datetime(2026, 9, 1, 12, 0, tzinfo=timezone.UTC)


def make_listing(places, **overrides):
    """A listing last seen before ``T0`` -- i.e. missed by a ``T0`` crawl."""
    fields = {
        'source': Source.DIVAR,
        'source_id': 'divar-missed',
        'source_url': 'https://divar.ir/v/divar-missed',
        'title': 'آپارتمان ۱۰۰ متری',
        'transaction_type': TransactionType.SALE,
        'property_type': PropertyType.APARTMENT,
        'province': places.province,
        'city': places.city,
        'last_seen_at': T0 - timedelta(days=1),
    }
    fields.update(overrides)
    return Listing.objects.create(**fields)


def seen_listing(places, **overrides):
    """A listing the crawl did see, so its scope is not treated as empty."""
    fields = {'source_id': 'divar-seen', 'last_seen_at': T0 + timedelta(days=5)}
    fields.update(overrides)
    return make_listing(places, **fields)


def finished_job(
    job_factory,
    *,
    started_at=T0,
    status=CrawlJobStatus.SUCCEEDED,
    details_fetched=1,
    **overrides,
):
    """A job that ran and finished just after ``started_at``."""
    job = job_factory(**overrides)
    job.transition_to(CrawlJobStatus.RUNNING, started_at=started_at)
    job.transition_to(
        status,
        finished_at=started_at + timedelta(minutes=1),
        details_fetched=details_fetched,
    )
    return job
