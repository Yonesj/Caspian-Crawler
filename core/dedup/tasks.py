"""Celery entry point for duplicate-candidate detection.

Like the lifecycle sweep this is pure database housekeeping: it compares rows we
already hold and never talks to a source.  It is gated twice — the beat entry
only exists when ``CELERY_BEAT_ENABLED`` and ``DEDUP_CANDIDATES_ENABLED`` are
both true, and the task re-checks the feature flag for direct invocation.
"""

from celery import shared_task
from django.conf import settings

from .services import detect_candidates


@shared_task(name='core.dedup.tasks.detect_duplicate_candidates')
def detect_duplicate_candidates_task() -> dict:
    """Record pending duplicate candidates for human review."""
    if not getattr(settings, 'DEDUP_CANDIDATES_ENABLED', False):
        return {'skipped': 'disabled'}
    result = detect_candidates()
    return {'skipped': False, **result.as_dict()}
