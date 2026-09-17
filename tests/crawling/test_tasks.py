import pytest

from core.crawling import tasks
from core.crawling.enums import CrawlJobStatus
from core.crawling.models import CrawlJob
from core.sources.errors import PermanentHTTPError, TransportError
from tests.crawling.conftest import FakeAdapter, make_detail, make_stub, page

pytestmark = pytest.mark.integration


@pytest.fixture
def patched_adapter(monkeypatch):
    def install(adapter):
        monkeypatch.setattr('core.crawling.runner.get_adapter', lambda source, **kw: adapter)
        return adapter

    return install


def test_task_runs_a_job_to_a_terminal_state(job_factory, patched_adapter):
    job = job_factory()
    patched_adapter(
        FakeAdapter(
            {'a1': make_detail('a1'), 'a2': make_detail('a2')},
            pages=[page(make_stub('a1'), make_stub('a2'))],
        )
    )

    result = tasks.run_crawl_job(job.pk)

    job.refresh_from_db()
    assert result['status'] == CrawlJobStatus.SUCCEEDED
    assert job.status == CrawlJobStatus.SUCCEEDED
    assert job.pages_fetched == 1
    assert job.listings_created == 2
    assert job.finished_at is not None
    assert job.report['duration_seconds'] is not None
    assert job.report['source_category'] == 'apartment-sell'
    assert job.events.filter(to_status=CrawlJobStatus.RUNNING).exists()


def test_a_redelivered_task_is_a_no_op(job_factory, patched_adapter):
    job = job_factory()
    patched_adapter(
        FakeAdapter({'a1': make_detail('a1')}, pages=[page(make_stub('a1'))])
    )
    tasks.run_crawl_job(job.pk)
    job.refresh_from_db()
    created = job.listings_created

    result = tasks.run_crawl_job(job.pk)

    job.refresh_from_db()
    assert result == {'job_id': job.pk, 'status': 'skipped'}
    assert job.listings_created == created
    assert CrawlJob.objects.count() == 1
    # Claimed exactly once, so the running transition appears exactly once.
    assert job.events.filter(to_status=CrawlJobStatus.RUNNING).count() == 1


def test_a_failed_detail_marks_the_job_partially_succeeded(
    job_factory, patched_adapter
):
    job = job_factory()
    patched_adapter(
        FakeAdapter(
            {'ok': make_detail('ok'), 'bad': PermanentHTTPError('gone', status_code=404)},
            pages=[page(make_stub('ok'), make_stub('bad'))],
        )
    )

    result = tasks.run_crawl_job(job.pk)

    job.refresh_from_db()
    assert result['status'] == CrawlJobStatus.PARTIALLY_SUCCEEDED
    assert job.status == CrawlJobStatus.PARTIALLY_SUCCEEDED
    assert job.errors == 1
    assert job.listings_created == 1


def test_a_failed_first_page_marks_the_job_failed(job_factory, patched_adapter):
    job = job_factory()
    patched_adapter(
        FakeAdapter({}, pages=[], list_error=TransportError('network down'))
    )

    result = tasks.run_crawl_job(job.pk)

    job.refresh_from_db()
    assert result['status'] == CrawlJobStatus.FAILED
    assert job.error == 'TransportError: network down'
    assert job.report['stopped_reason'] == 'TransportError: network down'


def test_scope_failure_is_recorded_without_touching_the_source(
    job_factory, places, patched_adapter
):
    from core.locations.models import SourceLocation

    job = job_factory()
    SourceLocation.objects.filter(source='divar').delete()

    result = tasks.run_crawl_job(job.pk)

    job.refresh_from_db()
    assert result['status'] == CrawlJobStatus.FAILED
    assert 'ScopeResolutionError' in job.error
    assert job.started_at is not None


def test_task_is_registered_under_a_stable_name():
    assert tasks.run_crawl_job.name == 'core.crawling.tasks.run_crawl_job'


def test_queue_job_marks_the_job_queued_and_runs_it_eagerly(
    job_factory, patched_adapter
):
    from core.crawling.models import queue_job

    job = job_factory()
    patched_adapter(
        FakeAdapter({'a1': make_detail('a1')}, pages=[page(make_stub('a1'))])
    )

    queue_job(job)

    job.refresh_from_db()
    assert job.queued_at is not None
    assert job.status == CrawlJobStatus.SUCCEEDED
    assert job.celery_task_id
