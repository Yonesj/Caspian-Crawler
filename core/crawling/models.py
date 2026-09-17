"""Crawl job domain.

A :class:`CrawlJob` records *what* an operator asked for and *how far* the crawl
got; the actual walking of a source happens in ``runner`` and the persistence of
listings in ``persistence``.  Keeping the job a plain record with an append-only
event log means its lifecycle is inspectable even when a worker dies mid-crawl.

The scope fields are shared with :class:`CrawlSchedule` so a periodic crawl is
just a job template that knows its next run time.
"""

from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from core.listings.enums import PropertyType, TransactionType
from core.locations.models import (
    City,
    LocationTargetMixin,
    Province,
    Region,
    exactly_one_location_target,
)
from core.sources.enums import Source

from .enums import (
    CLAIMABLE_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    CrawlJobEventLevel,
    CrawlJobStatus,
)


class CrawlScopeFields(LocationTargetMixin):
    """The saved scope of a crawl: where, what kind, how deep.

    ``source_external_id``/``source_category`` are snapshots of what the source
    layer resolved when the job was created, so a later change to reference data
    cannot rewrite history.
    """

    class Meta:
        abstract = True

    source = models.CharField(max_length=32, choices=Source.choices)
    transaction_type = models.CharField(
        max_length=16,
        choices=TransactionType.choices,
        default=TransactionType.UNSPECIFIED,
    )
    property_type = models.CharField(
        max_length=32, choices=PropertyType.choices, default=PropertyType.OTHER
    )

    province = models.ForeignKey(
        Province,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='%(class)s_scope',
    )
    city = models.ForeignKey(
        City,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='%(class)s_scope',
    )
    region = models.ForeignKey(
        Region,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='%(class)s_scope',
    )

    source_external_id = models.CharField(max_length=191, blank=True, default='')
    source_category = models.CharField(max_length=191, blank=True, default='')
    page_limit = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text='Maximum list pages to fetch; NULL means until the source runs out.',
    )


class CrawlJob(CrawlScopeFields):
    status = models.CharField(
        max_length=24, choices=CrawlJobStatus.choices, default=CrawlJobStatus.PENDING
    )
    celery_task_id = models.CharField(max_length=255, blank=True, default='')
    error = models.TextField(blank=True, default='')
    report = models.JSONField(
        default=dict,
        blank=True,
        help_text='Final counters and aggregated failures for this run.',
    )

    # Per-phase counters, written once when the job finishes.
    pages_fetched = models.PositiveIntegerField(default=0)
    stubs_seen = models.PositiveIntegerField(default=0)
    details_fetched = models.PositiveIntegerField(default=0)
    listings_created = models.PositiveIntegerField(default=0)
    listings_updated = models.PositiveIntegerField(default=0)
    listings_skipped = models.PositiveIntegerField(default=0)
    listings_out_of_scope = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='crawl_jobs',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'crawl job'
        verbose_name_plural = 'crawl jobs'
        constraints = [
            models.CheckConstraint(
                condition=exactly_one_location_target(),
                name='crawl_job_scope_exactly_one_target',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'created_at'], name='crawl_job_status_idx'),
            models.Index(fields=['source', 'status'], name='crawl_job_source_idx'),
        ]

    def __str__(self):
        return f'CrawlJob #{self.pk} {self.source} [{self.status}]'

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_JOB_STATUSES

    def transition_to(
        self,
        status,
        *,
        reason: str = '',
        level: str = CrawlJobEventLevel.INFO,
        message: str = '',
        context: dict | None = None,
        **fields,
    ) -> None:
        """Move to ``status``, persist ``fields`` and append an audit event.

        Every state change goes through here so the event log is a complete
        history rather than whatever the last writer happened to remember.
        """
        from_status = self.status
        self.status = status
        for name, value in fields.items():
            setattr(self, name, value)
        update_fields = {'status', 'updated_at', *fields}
        self.save(update_fields=sorted(update_fields))
        self.events.create(
            from_status=from_status,
            to_status=status,
            level=level,
            reason=reason,
            message=message or reason,
            context=context or {},
        )


class CrawlJobEvent(models.Model):
    """Append-only log of job state changes and significant crawl failures."""

    job = models.ForeignKey(CrawlJob, on_delete=models.CASCADE, related_name='events')
    from_status = models.CharField(
        max_length=24, choices=CrawlJobStatus.choices, blank=True, default=''
    )
    to_status = models.CharField(max_length=24, choices=CrawlJobStatus.choices)
    level = models.CharField(
        max_length=16, choices=CrawlJobEventLevel.choices, default=CrawlJobEventLevel.INFO
    )
    reason = models.CharField(max_length=255, blank=True, default='')
    message = models.TextField(blank=True, default='')
    context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'crawl job event'
        verbose_name_plural = 'crawl job events'

    def __str__(self):
        return f'{self.job_id}: {self.from_status or "-"} -> {self.to_status}'


class CrawlSchedule(CrawlScopeFields):
    """A job template that is re-run on an interval by Celery beat.

    Disabled by default and never seeded: periodic crawling stays opt-in, so
    bringing the stack up does not start loading third-party sites on its own.
    """

    name = models.CharField(max_length=120, unique=True)
    interval_minutes = models.PositiveIntegerField(default=360)
    is_enabled = models.BooleanField(default=False)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(
        null=True, blank=True, help_text='NULL means due as soon as it is enabled.'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'crawl schedule'
        verbose_name_plural = 'crawl schedules'
        constraints = [
            models.CheckConstraint(
                condition=exactly_one_location_target(),
                name='crawl_schedule_scope_exactly_one_target',
            ),
            models.CheckConstraint(
                condition=models.Q(interval_minutes__gte=1),
                name='crawl_schedule_interval_positive',
            ),
        ]

    def __str__(self):
        state = 'enabled' if self.is_enabled else 'disabled'
        return f'{self.name} ({self.source}, {state})'


# -- lifecycle helpers --------------------------------------------------------

def _resolve_snapshot(job) -> None:
    """Fill ``source_external_id``/``source_category`` from reference data.

    Imported lazily so the model module does not depend on the source layer at
    import time, and so a scope error surfaces as the source-layer typed error
    the caller already knows how to handle.
    """
    from .scope import build_scope

    scope = build_scope(job)
    job.source_external_id = scope.external_id
    job.source_category = scope.category or ''


def create_job(
    *,
    source: str,
    province=None,
    city=None,
    region=None,
    transaction_type: str = TransactionType.UNSPECIFIED,
    property_type: str = PropertyType.OTHER,
    page_limit: int | None = None,
    source_category: str = '',
    requested_by=None,
) -> CrawlJob:
    """Create a job, resolving and snapshotting its source scope up front.

    Resolving at creation (rather than in the worker) means an unmapped place or
    a disabled source fails immediately with a clear error instead of producing
    a queued job that can never run.
    """
    job = CrawlJob(
        source=str(source),
        province=province,
        city=city,
        region=region,
        transaction_type=str(transaction_type),
        property_type=str(property_type),
        page_limit=page_limit,
        source_category=source_category,
        requested_by=requested_by,
    )
    job.full_clean(exclude=['source_external_id', 'source_category'])
    _resolve_snapshot(job)
    job.save()
    return job


def claim_job(job_id: int, *, task_id: str = '') -> CrawlJob | None:
    """Atomically take ownership of a job, or return ``None``.

    ``select_for_update(skip_locked=True)`` is what makes a redelivered Celery
    task safe: the loser of the race sees the row locked, skips it, and becomes
    a no-op rather than crawling the same scope twice.
    """
    now = timezone.now()
    with transaction.atomic():
        job = (
            CrawlJob.objects.select_for_update(skip_locked=True)
            .filter(pk=job_id, status__in=CLAIMABLE_JOB_STATUSES)
            .first()
        )
        if job is None:
            return None
        job.transition_to(
            CrawlJobStatus.RUNNING,
            reason='claimed by a worker',
            started_at=now,
            celery_task_id=task_id,
        )
        return job


def queue_job(job: CrawlJob) -> CrawlJob:
    """Mark a pending job queued and publish it to the worker.

    Kept out of ``create_job`` so a caller can create a job, inspect it, and only
    then hand it to Celery.
    """
    from .tasks import run_crawl_job

    if job.status == CrawlJobStatus.PENDING:
        job.transition_to(
            CrawlJobStatus.QUEUED,
            reason='queued for a worker',
            queued_at=timezone.now(),
        )
    run_crawl_job.delay(job.pk)
    return job


def schedule_next_run(schedule: CrawlSchedule, *, now=None) -> None:
    now = now or timezone.now()
    schedule.last_run_at = now
    schedule.next_run_at = now + timedelta(minutes=schedule.interval_minutes)
    schedule.save(update_fields=['last_run_at', 'next_run_at', 'updated_at'])
