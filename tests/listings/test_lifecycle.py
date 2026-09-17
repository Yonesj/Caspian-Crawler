"""The miss policy: a listing not seen in a crawl ages, it never disappears."""

from datetime import timedelta

import pytest

from core.crawling.enums import CrawlJobStatus
from core.listings import lifecycle
from core.listings.enums import ListingStatus, PropertyType, TransactionType
from core.listings.lifecycle import SweepPolicy
from core.listings.models import Listing
from core.sources.enums import Source
from tests.listings.helpers import T0, finished_job, make_listing, seen_listing

pytestmark = pytest.mark.integration


def test_a_listing_not_seen_in_a_successful_crawl_becomes_stale(places, job_factory):
    listing = make_listing(places)
    seen_listing(places)
    job = finished_job(job_factory)

    result = lifecycle.sweep_listings(now=T0 + timedelta(hours=1))

    listing.refresh_from_db()
    job.refresh_from_db()
    assert listing.status == ListingStatus.STALE
    assert listing.consecutive_misses == 1
    assert result.jobs_swept == 1
    assert result.marked_stale == 1
    assert result.marked_delisted == 0
    assert job.swept_at is not None
    event = listing.status_events.get()
    assert (event.from_status, event.to_status) == (
        ListingStatus.ACTIVE,
        ListingStatus.STALE,
    )
    assert str(job.pk) in event.reason


def test_three_misses_in_a_row_delist_the_listing(places, job_factory):
    listing = make_listing(places)
    # One companion listing keeps every run's scope non-empty.
    seen_listing(places, last_seen_at=T0 + timedelta(days=5))

    for day in range(3):
        finished_job(job_factory, started_at=T0 + timedelta(days=day))
        lifecycle.sweep_listings(now=T0 + timedelta(days=day, hours=1))

    listing.refresh_from_db()
    assert listing.status == ListingStatus.DELISTED
    assert listing.consecutive_misses == 3
    transitions = [
        (event.from_status, event.to_status)
        for event in listing.status_events.order_by('id')
    ]
    assert transitions == [
        (ListingStatus.ACTIVE, ListingStatus.STALE),
        (ListingStatus.STALE, ListingStatus.DELISTED),
    ]


def test_a_listing_seen_by_the_crawl_is_left_alone(places, job_factory):
    listing = make_listing(places, last_seen_at=T0 + timedelta(minutes=1))
    finished_job(job_factory)

    result = lifecycle.sweep_listings(now=T0 + timedelta(hours=1))

    listing.refresh_from_db()
    assert listing.status == ListingStatus.ACTIVE
    assert listing.consecutive_misses == 0
    assert listing.status_events.count() == 0
    assert result.marked_stale == 0


def test_hidden_and_delisted_listings_are_never_touched(places, job_factory):
    hidden = make_listing(places, source_id='hidden', status=ListingStatus.HIDDEN)
    delisted = make_listing(
        places, source_id='delisted', status=ListingStatus.DELISTED, consecutive_misses=4
    )
    seen_listing(places)
    finished_job(job_factory)

    lifecycle.sweep_listings(now=T0 + timedelta(hours=1))

    hidden.refresh_from_db()
    delisted.refresh_from_db()
    assert hidden.status == ListingStatus.HIDDEN
    assert hidden.consecutive_misses == 0
    assert delisted.status == ListingStatus.DELISTED
    assert delisted.consecutive_misses == 4


def test_only_listings_matching_the_job_scope_are_swept(places, job_factory):
    in_scope = make_listing(places, source_id='in-scope')
    other_source = make_listing(places, source_id='other-source', source=Source.SHEYPOOR)
    other_type = make_listing(places, source_id='other-type', property_type=PropertyType.LAND)
    other_deal = make_listing(places, source_id='other-deal', transaction_type=TransactionType.RENT)
    seen_listing(places)
    finished_job(job_factory)

    lifecycle.sweep_listings(now=T0 + timedelta(hours=1))

    for row in (in_scope, other_source, other_type, other_deal):
        row.refresh_from_db()
    assert in_scope.status == ListingStatus.STALE
    assert other_source.status == ListingStatus.ACTIVE
    assert other_type.status == ListingStatus.ACTIVE
    assert other_deal.status == ListingStatus.ACTIVE


def test_an_unspecified_selection_sweeps_every_type_in_the_place(places, job_factory):
    land = make_listing(
        places,
        source_id='land',
        property_type=PropertyType.LAND,
        transaction_type=TransactionType.UNSPECIFIED,
    )
    seen_listing(places)
    finished_job(
        job_factory,
        property_type=PropertyType.OTHER,
        transaction_type=TransactionType.UNSPECIFIED,
    )

    lifecycle.sweep_listings(now=T0 + timedelta(hours=1))

    land.refresh_from_db()
    assert land.status == ListingStatus.STALE


def test_a_listing_in_another_place_is_not_swept(places, job_factory):
    from core.locations.models import City

    other_city = City.objects.create(
        province=places.province, code='amol', name_fa='آمل', name_en='Amol'
    )
    elsewhere = make_listing(places, source_id='elsewhere', city=other_city)
    seen_listing(places)
    finished_job(job_factory)

    lifecycle.sweep_listings(now=T0 + timedelta(hours=1))

    elsewhere.refresh_from_db()
    assert elsewhere.status == ListingStatus.ACTIVE
    assert elsewhere.consecutive_misses == 0


def test_a_crawl_that_persisted_nothing_is_skipped(places, job_factory):
    listing = make_listing(places)
    # details_fetched is the crawl's own count of persisted listings; zero means
    # the source returned nothing, which must not be read as "everything left".
    job = finished_job(job_factory, details_fetched=0)

    result = lifecycle.sweep_listings(
        now=T0 + timedelta(hours=1), policy=SweepPolicy(min_details=0)
    )

    listing.refresh_from_db()
    job.refresh_from_db()
    assert listing.status == ListingStatus.ACTIVE
    assert listing.consecutive_misses == 0
    assert result.jobs_swept == 0
    assert result.skipped == [{'job_id': job.pk, 'reason': 'crawl persisted no listings'}]
    # A skipped job is still marked so it is not re-evaluated on every run.
    assert job.swept_at is not None


def test_a_zero_detail_crawl_is_not_even_eligible(places, job_factory):
    listing = make_listing(places)
    finished_job(job_factory, details_fetched=0)

    result = lifecycle.sweep_listings(now=T0 + timedelta(hours=1))

    listing.refresh_from_db()
    assert result.jobs_considered == 0
    assert result.skipped == []
    assert listing.status == ListingStatus.ACTIVE


def test_a_crawl_whose_rows_are_all_out_of_scope_is_skipped(places, job_factory):
    listing = make_listing(places, last_seen_at=T0 - timedelta(days=1))
    # The job persisted something (details_fetched=4) but nothing it can see in
    # its own scope, so its silence says nothing about this listing.
    job = finished_job(job_factory, details_fetched=4, property_type=PropertyType.LAND)

    result = lifecycle.sweep_listings(now=T0 + timedelta(hours=1))

    listing.refresh_from_db()
    job.refresh_from_db()
    assert listing.status == ListingStatus.ACTIVE
    assert job.swept_at is not None
    assert result.jobs_swept == 0
    assert result.skipped[0]['job_id'] == job.pk
    assert result.skipped[0]['reason'] == 'crawl observed no in-scope listings'


def test_a_job_is_swept_at_most_once(places, job_factory):
    listing = make_listing(places)
    seen_listing(places)
    finished_job(job_factory)

    first = lifecycle.sweep_listings(now=T0 + timedelta(hours=1))
    second = lifecycle.sweep_listings(now=T0 + timedelta(hours=2))

    listing.refresh_from_db()
    assert first.jobs_swept == 1
    assert second.jobs_swept == 0
    assert second.jobs_considered == 0
    assert listing.consecutive_misses == 1


def test_only_succeeded_jobs_are_eligible(places, job_factory):
    make_listing(places)
    seen_listing(places)
    finished_job(job_factory, status=CrawlJobStatus.PARTIALLY_SUCCEEDED)
    finished_job(job_factory, status=CrawlJobStatus.FAILED)

    result = lifecycle.sweep_listings(now=T0 + timedelta(hours=1))

    assert result.jobs_considered == 0
    assert result.jobs_swept == 0
    assert Listing.objects.get(source_id='divar-missed').status == ListingStatus.ACTIVE


def test_dry_run_reports_without_writing(places, job_factory):
    listing = make_listing(places)
    seen_listing(places)
    job = finished_job(job_factory)

    result = lifecycle.sweep_listings(now=T0 + timedelta(hours=1), dry_run=True)

    listing.refresh_from_db()
    job.refresh_from_db()
    assert result.dry_run is True
    assert result.marked_stale == 1
    assert result.jobs_swept == 1
    assert listing.status == ListingStatus.ACTIVE
    assert listing.consecutive_misses == 0
    assert job.swept_at is None


def test_sweep_is_limited_and_can_target_one_job(places, job_factory):
    seen_listing(places, last_seen_at=T0 + timedelta(days=5))
    first = finished_job(job_factory)
    second = finished_job(job_factory, started_at=T0 + timedelta(hours=2))

    limited = lifecycle.sweep_listings(now=T0 + timedelta(hours=5), limit=1)
    targeted = lifecycle.sweep_listings(now=T0 + timedelta(hours=5), job_id=second.pk)

    first.refresh_from_db()
    second.refresh_from_db()
    assert limited.jobs_swept == 1
    assert first.swept_at is not None
    assert targeted.jobs_swept == 1
    assert second.swept_at is not None


def test_a_listing_seen_again_starts_counting_from_zero(places):
    from core.crawling.persistence import upsert_listing
    from core.normalization.dto import NormalizedListing

    listing = make_listing(places, consecutive_misses=2, status=ListingStatus.STALE)

    upsert_listing(
        NormalizedListing(
            source=Source.DIVAR,
            source_id='divar-missed',
            source_url='https://divar.ir/v/divar-missed',
            title='آپارتمان ۱۰۰ متری',
            transaction_type=TransactionType.SALE,
            property_type=PropertyType.APARTMENT,
            city_id=places.city.pk,
        ),
        seen_at=T0 + timedelta(minutes=5),
    )

    listing.refresh_from_db()
    assert listing.status == ListingStatus.ACTIVE
    assert listing.consecutive_misses == 0


def test_policy_reads_settings_and_keeps_the_thresholds_sane(settings):
    settings.LISTING_STALE_AFTER_MISSES = 0
    settings.LISTING_DELISTED_AFTER_MISSES = 0
    settings.LISTING_SWEEP_MIN_DETAILS = 2

    policy = SweepPolicy.from_settings()

    assert policy.stale_after_misses == 1
    assert policy.delisted_after_misses == 1
    assert policy.min_details == 2
