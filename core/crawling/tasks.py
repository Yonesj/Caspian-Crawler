"""Celery entry points for the crawl pipeline.

Two tasks live here, with deliberately different roles:

* ``run_crawl_job`` performs the crawl on a worker and owns the job's terminal
  state.  It is idempotent: a redelivered message for a job someone else owns
  (or one that already finished) is a no-op.
* ``dispatch_due_schedules`` runs on the Celery beat tick and only decides which
  saved schedules are due; it never performs HTTP itself.
"""

import logging

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.sources.errors import SourceError

from .enums import CrawlJobEventLevel, CrawlJobStatus
from .models import CrawlSchedule, claim_job, create_job, schedule_next_run
from .runner import run_job
from .scope import build_scope

logger = logging.getLogger('caspian_crawler.crawl')


@shared_task(bind=True, acks_late=True, name='core.crawling.tasks.run_crawl_job')
def run_crawl_job(self, job_id: int) -> dict:
    """Crawl one job and record its outcome."""
    job = claim_job(job_id, task_id=getattr(self.request, 'id', '') or '')
    if job is None:
        # Already running elsewhere, or already finished.  Redelivery is normal
        # with acks_late, so this is not an error.
        return {'job_id': job_id, 'status': 'skipped'}

    return execute_job(job)


def execute_job(job) -> dict:
    """Run an already-claimed job to completion and record its outcome.

    Shared by the Celery task and the worker-less management command so both
    take exactly the same code path.
    """
    try:
        scope = build_scope(job)
    except SourceError as exc:
        return _scope_failed(job, exc)
    return finish_job(job, run_job(job, scope=scope))


def _scope_failed(job, exc: SourceError) -> dict:
    message = f'{type(exc).__name__}: {exc}'
    job.transition_to(
        CrawlJobStatus.FAILED,
        reason='scope could not be resolved',
        level=CrawlJobEventLevel.ERROR,
        error=message,
        finished_at=timezone.now(),
        report={'stopped_reason': message, 'errors': []},
    )
    logger.error('crawl job %s could not start: %s', job.pk, message)
    return {'job_id': job.pk, 'status': job.status, 'error': message}


def finish_job(job, report) -> dict:
    counts = report.counts
    status = _final_status(report)
    finished_at = timezone.now()
    duration = (
        (finished_at - job.started_at).total_seconds() if job.started_at else None
    )
    payload = report.as_dict()
    payload['duration_seconds'] = round(duration, 2) if duration is not None else None
    payload['source_external_id'] = job.source_external_id
    payload['source_category'] = job.source_category

    level = CrawlJobEventLevel.INFO
    if status == CrawlJobStatus.FAILED:
        level = CrawlJobEventLevel.ERROR
    elif status == CrawlJobStatus.PARTIALLY_SUCCEEDED:
        level = CrawlJobEventLevel.WARNING

    job.transition_to(
        status,
        reason=report.stopped_reason or _reason(status, counts),
        level=level,
        error=report.stopped_reason or '',
        finished_at=finished_at,
        report=payload,
        pages_fetched=counts.pages,
        stubs_seen=counts.stubs,
        details_fetched=counts.details,
        listings_created=counts.created,
        listings_updated=counts.updated,
        listings_skipped=counts.skipped,
        listings_out_of_scope=counts.out_of_scope,
        errors=report.error_total,
    )

    logger.info(
        'crawl job %s finished %s: pages=%s created=%s updated=%s failed=%s',
        job.pk,
        status,
        counts.pages,
        counts.created,
        counts.updated,
        counts.failed,
    )
    return {'job_id': job.pk, 'status': status, **payload}


def _final_status(report) -> str:
    counts = report.counts
    saved = counts.created + counts.updated
    if report.stopped_reason:
        return (
            CrawlJobStatus.PARTIALLY_SUCCEEDED
            if saved
            else CrawlJobStatus.FAILED
        )
    if counts.failed:
        return (
            CrawlJobStatus.PARTIALLY_SUCCEEDED
            if counts.details
            else CrawlJobStatus.FAILED
        )
    return CrawlJobStatus.SUCCEEDED


def _reason(status, counts) -> str:
    if status == CrawlJobStatus.SUCCEEDED:
        return f'crawl completed; {counts.created + counts.updated} listings persisted'
    return (
        f'{counts.failed} listing(s) failed, {counts.created + counts.updated} persisted'
    )


@shared_task(name='core.crawling.tasks.dispatch_due_schedules')
def dispatch_due_schedules() -> int:
    """Enqueue a crawl job for every enabled schedule that is due.

    Only ever scheduled by beat, and only when ``CELERY_BEAT_ENABLED`` put the
    periodic entry in the beat schedule (see ``config/settings/base.py``), so
    this task is inert unless an operator opted in *and* saved a schedule.
    """
    return dispatch_due(now=timezone.now())


def dispatch_due(*, now=None) -> int:
    """Claim due schedules and enqueue their jobs; returns how many were sent.

    Job creation is committed before the tasks are published so a worker can
    never pick up an id whose row does not exist yet.
    """
    now = now or timezone.now()
    job_ids: list[int] = []

    with transaction.atomic():
        due = (
            CrawlSchedule.objects.select_for_update(skip_locked=True)
            .filter(is_enabled=True)
            .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
            .order_by('next_run_at', 'id')[:50]
        )
        for schedule in due:
            try:
                job = create_job(
                    source=schedule.source,
                    province=schedule.province,
                    city=schedule.city,
                    region=schedule.region,
                    transaction_type=schedule.transaction_type,
                    property_type=schedule.property_type,
                    page_limit=schedule.page_limit,
                    source_category=schedule.source_category,
                )
            except SourceError as exc:
                # A broken mapping must not block every other schedule, and it
                # must not be retried on every beat tick either.
                logger.error('schedule %s could not create a job: %s', schedule.name, exc)
            else:
                job_ids.append(job.pk)
            schedule_next_run(schedule, now=now)

    for job_id in job_ids:
        run_crawl_job.delay(job_id)
    return len(job_ids)
