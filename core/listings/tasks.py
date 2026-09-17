"""Celery entry point for the listing lifecycle sweep.

The sweep is periodic housekeeping over our own database: it never touches a
source, so it is safe to run on a schedule.  It is still gated twice — beat must
be opted in (``CELERY_BEAT_ENABLED`` puts the entry in the schedule at all) and
``LISTING_SWEEP_ENABLED`` must be true — so an operator can keep the crawl
schedule without ageing listings.
"""

from celery import shared_task
from django.conf import settings

from . import lifecycle


@shared_task(name='core.listings.tasks.sweep_listings')
def sweep_listings_task() -> dict:
    """Charge a miss to every listing a finished crawl did not see."""
    if not getattr(settings, 'LISTING_SWEEP_ENABLED', False):
        return {'skipped': 'disabled'}
    result = lifecycle.sweep_listings()
    return {'skipped': False, **result.as_dict()}
