from datetime import timedelta

import pytest
from django.utils import timezone

from core.crawling import tasks
from core.crawling.models import CrawlJob, CrawlSchedule
from core.listings.enums import PropertyType, TransactionType
from core.locations.models import SourceLocation

pytestmark = pytest.mark.integration

NOW = timezone.now()


def make_schedule(places, **overrides):
    values = {
        'name': overrides.pop('name', 'nightly-sari'),
        'source': 'divar',
        'city': places.city,
        'transaction_type': TransactionType.SALE,
        'property_type': PropertyType.APARTMENT,
        'interval_minutes': 60,
        'is_enabled': True,
        'next_run_at': NOW - timedelta(minutes=5),
    }
    values.update(overrides)
    return CrawlSchedule.objects.create(**values)


@pytest.fixture
def enqueued(monkeypatch):
    """Record published task ids instead of running them."""
    calls: list[int] = []
    monkeypatch.setattr(tasks.run_crawl_job, 'delay', calls.append)
    return calls


def test_beat_entry_is_absent_until_an_operator_opts_in(settings):
    # Opt-in lives in the beat process's settings: with the flag off, beat has
    # no periodic entry to send, so a fresh stack never starts crawling.
    assert settings.CELERY_BEAT_ENABLED is False
    assert 'dispatch-due-crawl-schedules' not in settings.CELERY_BEAT_SCHEDULE


def test_tick_with_no_schedules_does_nothing(places, source_categories, enqueued):
    assert tasks.dispatch_due_schedules() == 0
    assert enqueued == []
    assert CrawlJob.objects.count() == 0


def test_a_due_schedule_creates_and_publishes_one_job(
    places, source_categories, enqueued
):
    schedule = make_schedule(places)

    assert tasks.dispatch_due_schedules() == 1

    job = CrawlJob.objects.get()
    assert job.source == 'divar'
    assert job.city_id == places.city.pk
    assert enqueued == [job.pk]
    schedule.refresh_from_db()
    assert schedule.last_run_at is not None
    assert schedule.next_run_at > NOW


def test_disabled_and_future_schedules_are_skipped(
    places, source_categories, enqueued
):
    make_schedule(places, name='disabled', is_enabled=False)
    make_schedule(places, name='future', next_run_at=NOW + timedelta(hours=1))

    assert tasks.dispatch_due_schedules() == 0
    assert CrawlJob.objects.count() == 0


def test_a_second_tick_does_not_re_run_the_same_schedule(
    places, source_categories, enqueued
):
    make_schedule(places)

    tasks.dispatch_due_schedules()
    assert tasks.dispatch_due_schedules() == 0

    assert CrawlJob.objects.count() == 1
    assert len(enqueued) == 1


def test_a_broken_scope_does_not_block_the_dispatch(
    places, source_categories, enqueued
):
    make_schedule(places)
    SourceLocation.objects.filter(source='divar').delete()

    assert tasks.dispatch_due_schedules() == 0
    assert CrawlJob.objects.count() == 0
    schedule = CrawlSchedule.objects.get()
    # The schedule advances instead of hot-looping on every beat tick.
    assert schedule.next_run_at > NOW
