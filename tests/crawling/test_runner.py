import pytest

from core.crawling.runner import run_job
from core.crawling.scope import build_scope
from core.listings.enums import PropertyType
from core.listings.models import Listing
from core.sources.errors import PermanentHTTPError, TransportError
from tests.crawling.conftest import (
    FakeAdapter,
    divar_fixture_details,
    make_detail,
    make_stub,
    page,
)

pytestmark = pytest.mark.integration


def test_counts_cover_pages_stubs_and_persistence(job_factory):
    job = job_factory()
    adapter = FakeAdapter(
        {
            'a1': make_detail('a1'),
            'a2': make_detail('a2'),
            'a3': make_detail('a3'),
        },
        pages=[
            page(make_stub('a1'), make_stub('a2'), number=1, has_next=True),
            # a2 repeats on page 2: identity is the source id, so it is skipped.
            page(make_stub('a2'), make_stub('a3'), number=2),
        ],
    )

    report = run_job(job, scope=build_scope(job), adapter=adapter)

    assert report.counts.pages == 2
    assert report.counts.stubs == 4
    assert report.counts.details == 3
    assert report.counts.created == 3
    assert report.counts.skipped == 1
    assert report.stopped_reason is None
    assert adapter.detail_calls.count('a2') == 1


def test_re_running_updates_instead_of_creating_duplicates(job_factory):
    job = job_factory()
    details = {'a1': make_detail('a1'), 'a2': make_detail('a2')}
    adapter = FakeAdapter(details, pages=[page(make_stub('a1'), make_stub('a2'))])

    first = run_job(job, scope=build_scope(job), adapter=adapter)
    second = run_job(job, scope=build_scope(job), adapter=adapter)

    assert (first.counts.created, first.counts.updated) == (2, 0)
    assert (second.counts.created, second.counts.updated) == (0, 2)
    assert Listing.objects.count() == 2


def test_one_bad_detail_does_not_abort_the_crawl(job_factory):
    job = job_factory()
    adapter = FakeAdapter(
        {
            'ok1': make_detail('ok1'),
            'bad': PermanentHTTPError('gone', status_code=404),
            'ok2': make_detail('ok2'),
        },
        pages=[page(make_stub('ok1'), make_stub('bad'), make_stub('ok2'))],
    )

    report = run_job(job, scope=build_scope(job), adapter=adapter)

    assert report.counts.details == 2
    assert report.counts.created == 2
    assert report.counts.failed == 1
    assert report.stopped_reason is None
    assert report.errors[0]['source_id'] == 'bad'
    assert report.errors[0]['type'] == 'PermanentHTTPError'


def test_a_list_page_failure_stops_the_crawl_and_is_reported(job_factory):
    job = job_factory()
    adapter = FakeAdapter(
        {'a1': make_detail('a1')},
        pages=[page(make_stub('a1'))],
        list_error=TransportError('connection reset'),
    )

    report = run_job(job, scope=build_scope(job), adapter=adapter)

    assert report.counts.pages == 0
    assert report.stopped_reason == 'TransportError: connection reset'
    assert report.errors[0]['source_id'] == 'list-page'


def test_listings_outside_the_requested_type_are_counted_not_dropped(job_factory):
    job = job_factory(transaction_type='sale', property_type=PropertyType.APARTMENT)
    adapter = FakeAdapter(
        {
            'sale': make_detail('sale'),
            'rent': make_detail('rent', category_path=('apartment-rent',)),
        },
        pages=[page(make_stub('sale'), make_stub('rent'))],
    )

    report = run_job(job, scope=build_scope(job), adapter=adapter)

    assert report.counts.created == 2
    assert report.counts.out_of_scope == 1


def test_real_fixture_details_flow_through_to_listings(job_factory):
    job = job_factory()
    details = dict(divar_fixture_details('gar-qQRf', 'gas6SGcg'))
    adapter = FakeAdapter(
        details,
        pages=[page(make_stub('gar-qQRf'), make_stub('gas6SGcg'))],
    )

    report = run_job(job, scope=build_scope(job), adapter=adapter)

    listing = Listing.objects.get(source_id='gar-qQRf')
    assert listing.sale_price == 6950000000
    assert listing.property_type == PropertyType.APARTMENT
    assert report.counts.created == 2
    # gas6SGcg is a rent listing, the job asked for a sale.
    assert report.counts.out_of_scope == 1
