"""Drive one crawl job: list pages -> details -> normalization -> persistence.

Failure policy:

* a single unparseable or unavailable detail is counted, logged and skipped --
  one bad listing must not cost the whole crawl;
* a list page that exhausts the transport's retry budget stops the crawl, and
  the caller decides whether the job is "partially succeeded" or "failed";
* nothing here raises for a *listing* problem, so the caller always gets a
  report to persist.
"""

import logging
from dataclasses import asdict, dataclass, field

from django.utils import timezone

from core.listings.enums import PropertyType, TransactionType
from core.normalization import LocationIndex, normalize_detail
from core.sources.errors import SourceError
from core.sources.registry import get_adapter

from .persistence import upsert_listing

logger = logging.getLogger('caspian_crawler.crawl')

MAX_REPORTED_ERRORS = 50


@dataclass
class CrawlCounts:
    """What the crawl did, phase by phase."""

    pages: int = 0
    stubs: int = 0
    details: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    out_of_scope: int = 0


@dataclass(frozen=True)
class CrawlReport:
    counts: CrawlCounts
    errors: list[dict] = field(default_factory=list)
    error_total: int = 0
    stopped_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            **asdict(self.counts),
            'errors': self.errors,
            'error_total': self.error_total,
            'stopped_reason': self.stopped_reason,
        }


class _ErrorLog:
    """Bounded, deduplicated error collection.

    A crawl can hit the same failure for hundreds of listings; the report keeps
    one entry per ``(source_id, exception type)`` rather than growing without
    limit.
    """

    def __init__(self, limit: int = MAX_REPORTED_ERRORS):
        self._limit = limit
        self._seen: set[tuple[str, str]] = set()
        self.entries: list[dict] = []
        self.total = 0

    def record(self, source_id, exc: Exception) -> None:
        self.total += 1
        key = (str(source_id), type(exc).__name__)
        if key in self._seen or len(self.entries) >= self._limit:
            return
        self._seen.add(key)
        self.entries.append(
            {
                'source_id': str(source_id),
                'type': type(exc).__name__,
                'message': str(exc)[:500],
            }
        )


def run_job(job, *, scope, adapter=None, index=None, now=None) -> CrawlReport:
    """Walk ``scope`` and persist what the source returns."""
    adapter = adapter if adapter is not None else get_adapter(job.source)
    index = index if index is not None else LocationIndex.load()
    seen_at = now or timezone.now()

    counts = CrawlCounts()
    errors = _ErrorLog()
    stopped_reason: str | None = None
    seen_ids: set[str] = set()

    try:
        for page in adapter.iter_list_pages(scope):
            counts.pages += 1
            for stub in page.items:
                counts.stubs += 1
                if stub.source_id in seen_ids:
                    # The same listing can appear on several pages; identity is
                    # the source id, so it is processed once per run.
                    counts.skipped += 1
                    continue
                seen_ids.add(stub.source_id)
                _process_stub(
                    job, stub, adapter, index, counts, errors, seen_at=seen_at
                )
    except SourceError as exc:
        stopped_reason = f'{type(exc).__name__}: {exc}'
        errors.record('list-page', exc)
        logger.error(
            'crawl job %s stopped on a source error: %s', job.pk, stopped_reason
        )

    return CrawlReport(
        counts=counts,
        errors=errors.entries,
        error_total=errors.total,
        stopped_reason=stopped_reason,
    )


def _process_stub(job, stub, adapter, index, counts, errors, *, seen_at) -> None:
    try:
        detail = adapter.fetch_detail(stub.source_id, url=stub.url)
        normalized = normalize_detail(detail, index=index)
        outcome = upsert_listing(
            normalized,
            raw=detail.raw,
            image_urls=detail.image_urls,
            seen_at=seen_at,
        )
    except SourceError as exc:
        counts.failed += 1
        errors.record(stub.source_id, exc)
        logger.warning(
            'crawl job %s: %s:%s failed: %s',
            job.pk,
            job.source,
            stub.source_id,
            exc,
        )
        return

    counts.details += 1
    if outcome.created:
        counts.created += 1
    else:
        counts.updated += 1
    if _outside_requested_type(job, normalized):
        counts.out_of_scope += 1


def _outside_requested_type(job, normalized) -> bool:
    """Whether the listing disagrees with the job's requested transaction/property.

    Such listings are still persisted -- they are real listings in the crawled
    place -- but counted so the report explains why a "sale apartments" job
    returned rows the operator did not ask for.
    """
    if (
        job.property_type != PropertyType.OTHER
        and normalized.property_type != job.property_type
    ):
        return True
    return (
        job.transaction_type != TransactionType.UNSPECIFIED
        and normalized.transaction_type != job.transaction_type
    )
