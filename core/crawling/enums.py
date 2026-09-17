"""Crawl job vocabulary.

Job status is deliberately richer than "running / not running": a crawl that
saved part of its scope before a source failed is not the same as one that never
reached the source, and the difference matters to whoever re-runs it.
"""

from django.db import models


class CrawlJobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    QUEUED = "queued", "Queued for a worker"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded", "Partially succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class CrawlJobEventLevel(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"


TERMINAL_JOB_STATUSES = frozenset(
    {
        CrawlJobStatus.SUCCEEDED,
        CrawlJobStatus.PARTIALLY_SUCCEEDED,
        CrawlJobStatus.FAILED,
        CrawlJobStatus.CANCELLED,
    }
)

# Only these may be claimed by a worker; anything else means someone else
# already owns the job or it is done.
CLAIMABLE_JOB_STATUSES = frozenset({CrawlJobStatus.PENDING, CrawlJobStatus.QUEUED})
