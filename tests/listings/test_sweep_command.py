"""Operator entry points for the sweep: a command, a task and a beat entry."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.listings import tasks
from core.listings.enums import ListingStatus
from config.settings.base import build_beat_schedule
from tests.listings.helpers import T0, finished_job, make_listing, seen_listing

pytestmark = pytest.mark.integration


def test_command_sweeps_and_reports(places, job_factory, capsys):
    listing = make_listing(places)
    seen_listing(places)
    finished_job(job_factory)

    call_command('sweep_listings')

    listing.refresh_from_db()
    assert listing.status == ListingStatus.STALE
    assert 'swept 1 job(s)' in capsys.readouterr().out


def test_command_dry_run_writes_nothing(places, job_factory, capsys):
    listing = make_listing(places)
    seen_listing(places)
    job = finished_job(job_factory)

    call_command('sweep_listings', '--dry-run')

    listing.refresh_from_db()
    job.refresh_from_db()
    assert listing.status == ListingStatus.ACTIVE
    assert job.swept_at is None
    assert 'dry run' in capsys.readouterr().out


def test_command_can_target_one_job(places, job_factory):
    listing = make_listing(places)
    seen_listing(places)
    first = finished_job(job_factory)
    second = finished_job(job_factory, started_at=T0 + timedelta(hours=2))

    call_command('sweep_listings', '--job-id', str(second.pk))

    listing.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.swept_at is None
    assert second.swept_at is not None


def test_command_honours_limit_and_rejects_bad_input(places, job_factory):
    seen_listing(places)
    finished_job(job_factory)
    finished_job(job_factory, started_at=T0 + timedelta(hours=2))

    call_command('sweep_listings', '--limit', '1')

    assert [job.swept_at is not None for job in _jobs()].count(True) == 1
    with pytest.raises(CommandError):
        call_command('sweep_listings', '--limit', '0')


def _jobs():
    from core.crawling.models import CrawlJob

    return list(CrawlJob.objects.order_by('id'))


def test_task_is_inert_until_the_feature_is_enabled(settings, places, job_factory):
    settings.LISTING_SWEEP_ENABLED = False
    listing = make_listing(places)
    seen_listing(places)
    finished_job(job_factory)

    result = tasks.sweep_listings_task()

    listing.refresh_from_db()
    assert result == {'skipped': 'disabled'}
    assert listing.status == ListingStatus.ACTIVE


def test_task_ages_listings_when_enabled(settings, places, job_factory):
    settings.LISTING_SWEEP_ENABLED = True
    listing = make_listing(places)
    seen_listing(places)
    finished_job(job_factory)

    result = tasks.sweep_listings_task()

    listing.refresh_from_db()
    assert result['jobs_swept'] == 1
    assert listing.status == ListingStatus.STALE


def test_beat_schedule_requires_both_switches():
    gated = build_beat_schedule(
        beat_enabled=True,
        tick_seconds=60,
        listing_sweep_enabled=False,
        listing_sweep_interval=3600,
        dedup_enabled=False,
        dedup_interval=86400,
    )
    assert gated == {'dispatch-due-crawl-schedules': {
        'task': 'core.crawling.tasks.dispatch_due_schedules',
        'schedule': 60.0,
    }}

    enabled = build_beat_schedule(
        beat_enabled=True,
        tick_seconds=60,
        listing_sweep_enabled=True,
        listing_sweep_interval=3600,
        dedup_enabled=True,
        dedup_interval=86400,
    )
    assert enabled['sweep-listing-lifecycle']['task'] == 'core.listings.tasks.sweep_listings'
    assert enabled['detect-duplicate-candidates']['schedule'] == 86400.0

    off = build_beat_schedule(
        beat_enabled=False,
        tick_seconds=60,
        listing_sweep_enabled=True,
        listing_sweep_interval=3600,
        dedup_enabled=True,
        dedup_interval=86400,
    )
    assert off == {}


def test_defaults_keep_periodic_work_off(settings):
    # Beat itself is the first opt-in, so the default settings carry no
    # periodic entries at all.
    assert settings.CELERY_BEAT_ENABLED is False
    assert settings.CELERY_BEAT_SCHEDULE == {}
