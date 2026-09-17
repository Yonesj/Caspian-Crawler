import pytest
from django.db import IntegrityError, transaction

from core.crawling import models
from core.crawling.enums import CrawlJobStatus
from core.listings.enums import PropertyType, TransactionType
from core.sources.enums import Source

pytestmark = pytest.mark.integration


def test_new_job_defaults_are_pending_and_empty(job_factory):
    job = job_factory()

    assert job.status == CrawlJobStatus.PENDING
    assert job.is_terminal is False
    assert job.report == {}
    assert job.listings_created == 0
    assert job.pages_fetched == 0
    # The scope is snapshotted at creation, so a later data change cannot
    # rewrite what this job was asked to do.
    assert job.source_external_id == '22'
    assert job.source_category == 'apartment-sell'


def test_create_job_rejects_a_half_built_scope(places):
    with pytest.raises(Exception):
        models.create_job(
            source=Source.DIVAR, province=places.province, city=places.city
        )


def test_scope_must_point_at_exactly_one_level(job_factory, places):
    job = job_factory()

    with pytest.raises(IntegrityError), transaction.atomic():
        models.CrawlJob.objects.filter(pk=job.pk).update(region=places.region)


def test_transition_appends_an_audit_event(job_factory):
    job = job_factory()

    job.transition_to(CrawlJobStatus.RUNNING, reason='claimed by a worker')

    event = job.events.get()
    assert event.from_status == CrawlJobStatus.PENDING
    assert event.to_status == CrawlJobStatus.RUNNING
    assert event.reason == 'claimed by a worker'


def test_claim_job_hands_the_job_to_one_worker_only(job_factory):
    job = job_factory()

    claimed = models.claim_job(job.pk, task_id='task-1')

    assert claimed is not None
    assert claimed.status == CrawlJobStatus.RUNNING
    assert claimed.started_at is not None
    # A second worker (or a redelivered message) gets nothing.
    assert models.claim_job(job.pk) is None


def test_claim_job_ignores_terminal_jobs(job_factory):
    job = job_factory()
    job.transition_to(CrawlJobStatus.SUCCEEDED)

    assert models.claim_job(job.pk) is None


def test_create_job_stores_the_requested_selection(job_factory):
    job = job_factory(
        transaction_type=TransactionType.RENT, property_type=PropertyType.COMMERCIAL
    )

    assert job.property_type == PropertyType.COMMERCIAL
    # Resolved from reference data (the seeded Divar slug), not hardcoded.
    assert job.source_category == 'shop-rent'


def test_create_job_fails_fast_when_the_place_is_unmapped(places):
    from core.crawling.errors import ScopeResolutionError

    # Sheypoor has a city mapping in the fixtures but no province mapping, so
    # the fallback chain runs out and the job is refused up front.
    with pytest.raises(ScopeResolutionError):
        models.create_job(source=Source.SHEYPOOR, province=places.province)
