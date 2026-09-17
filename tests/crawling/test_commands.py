import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.crawling import tasks
from core.crawling.enums import CrawlJobStatus
from core.crawling.models import CrawlJob
from core.listings.models import Listing
from tests.crawling.conftest import FakeAdapter, make_detail, make_stub, page

pytestmark = pytest.mark.integration


def test_create_command_registers_a_scoped_job(places, source_categories):
    call_command(
        'create_crawl_job',
        '--source', 'divar',
        '--city', 'sari',
        '--transaction', 'sale',
        '--property', 'apartment',
        '--pages', '2',
        '--no-enqueue',
    )

    job = CrawlJob.objects.get()
    assert job.status == CrawlJobStatus.PENDING
    assert job.city_id == places.city.pk
    assert job.source_external_id == '22'
    assert job.source_category == 'apartment-sell'
    assert job.page_limit == 2


def test_create_command_enqueues_by_default(places, source_categories, monkeypatch):
    published: list[int] = []
    monkeypatch.setattr(tasks.run_crawl_job, 'delay', published.append)

    call_command('create_crawl_job', '--source', 'divar', '--city', 'sari')

    job = CrawlJob.objects.get()
    assert published == [job.pk]
    assert job.status == CrawlJobStatus.QUEUED


def test_create_command_rejects_an_unknown_place(places, source_categories):
    with pytest.raises(CommandError):
        call_command('create_crawl_job', '--source', 'divar', '--city', 'nowhere')


def test_create_command_requires_a_scope(source_categories):
    with pytest.raises(CommandError):
        call_command('create_crawl_job', '--source', 'divar', '--no-enqueue')


def test_create_command_rejects_a_zero_page_limit(places, source_categories):
    with pytest.raises(CommandError):
        call_command(
            'create_crawl_job', '--source', 'divar', '--city', 'sari', '--pages', '0'
        )


def test_run_command_executes_a_pending_job_inline(
    job_factory, monkeypatch, capsys
):
    job = job_factory()
    adapter = FakeAdapter({'a1': make_detail('a1')}, pages=[page(make_stub('a1'))])
    monkeypatch.setattr('core.crawling.runner.get_adapter', lambda source, **kw: adapter)

    call_command('run_crawl_jobs')

    job.refresh_from_db()
    assert job.status == CrawlJobStatus.SUCCEEDED
    assert job.listings_created == 1
    assert 'finished' in capsys.readouterr().out


def test_run_command_is_idempotent(job_factory, monkeypatch):
    job = job_factory()
    adapter = FakeAdapter({'a1': make_detail('a1')}, pages=[page(make_stub('a1'))])
    monkeypatch.setattr('core.crawling.runner.get_adapter', lambda source, **kw: adapter)

    call_command('run_crawl_jobs')
    call_command('run_crawl_jobs')

    assert Listing.objects.count() == 1
    assert CrawlJob.objects.count() == 1
