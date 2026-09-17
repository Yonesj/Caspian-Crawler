"""Detection records evidence; review records a human decision. Nothing merges."""

import pytest

from core.dedup import services
from core.dedup.enums import DuplicateCanonical, DuplicateStatus
from core.dedup.models import DuplicateCandidate
from core.listings.enums import ListingStatus
from core.listings.models import Listing
from core.locations.models import City
from tests.dedup.helpers import matching_pair
from tests.listings.helpers import make_listing

pytestmark = pytest.mark.integration


def test_detection_records_one_pending_candidate_per_pair(places):
    left, right = matching_pair(places)

    result = services.detect_candidates()

    assert (result.buckets, result.listings, result.pairs_evaluated) == (1, 2, 1)
    assert (result.matches, result.candidates_created) == (1, 1)
    candidate = DuplicateCandidate.objects.get()
    assert candidate.left_id == min(left.pk, right.pk)
    assert candidate.right_id == max(left.pk, right.pk)
    assert candidate.status == DuplicateStatus.PENDING
    assert candidate.canonical is None
    assert candidate.score == 100
    assert [signal['name'] for signal in candidate.signals] == [
        'area', 'price', 'title', 'published',
    ]


def test_detection_is_idempotent(places):
    matching_pair(places)
    services.detect_candidates()

    again = services.detect_candidates()

    assert DuplicateCandidate.objects.count() == 1
    assert again.candidates_created == 0
    assert again.candidates_updated == 1


def test_unrelated_listings_are_not_candidates(places):
    make_listing(
        places, source_id='divar-a', title='آپارتمان ۱۰۰ متری', area_sqm=100,
        sale_price=3_000_000_000,
    )
    make_listing(
        places, source_id='sheypoor-b', source='sheypoor', title='دفتر کار اداری',
        area_sqm=40, sale_price=9_000_000_000,
    )

    result = services.detect_candidates()

    assert result.pairs_evaluated == 1
    assert result.matches == 0
    assert DuplicateCandidate.objects.count() == 0


def test_two_listings_from_the_same_source_are_never_candidates(places):
    for index in range(2):
        make_listing(
            places, source_id=f'divar-{index}', title='آپارتمان ۱۰۰ متری',
            area_sqm=100, sale_price=3_000_000_000,
        )

    result = services.detect_candidates()

    assert result.matches == 0
    assert DuplicateCandidate.objects.count() == 0


def test_hidden_and_already_linked_listings_are_excluded(places):
    left, right = matching_pair(places)
    right.status = ListingStatus.HIDDEN
    right.save(update_fields=['status'])

    assert services.detect_candidates().matches == 0

    right.status = ListingStatus.ACTIVE
    right.duplicate_of = left
    right.save(update_fields=['status', 'duplicate_of'])

    assert services.detect_candidates().matches == 0


def test_confirming_links_the_loser_and_keeps_both_rows(places):
    left, right = matching_pair(places)
    services.detect_candidates()
    candidate = DuplicateCandidate.objects.get()

    services.confirm_candidate(candidate, canonical=DuplicateCanonical.LEFT)

    left.refresh_from_db()
    right.refresh_from_db()
    candidate.refresh_from_db()
    assert candidate.status == DuplicateStatus.CONFIRMED
    assert candidate.canonical == DuplicateCanonical.LEFT
    assert candidate.reviewed_at is not None
    assert right.duplicate_of_id == left.pk
    assert left.duplicate_of_id is None
    assert Listing.objects.count() == 2  # nothing merged, nothing deleted
    assert left.title == 'آپارتمان ۱۰۰ متری در ساری'


def test_confirming_can_keep_the_other_side(places):
    left, right = matching_pair(places)
    services.detect_candidates()

    services.confirm_candidate(
        DuplicateCandidate.objects.get(), canonical=DuplicateCanonical.RIGHT
    )

    left.refresh_from_db()
    assert left.duplicate_of_id == right.pk


def test_a_rejected_verdict_survives_redetection(places):
    matching_pair(places)
    services.detect_candidates()
    candidate = DuplicateCandidate.objects.get()

    services.reject_candidate(candidate, note='different floor')
    again = services.detect_candidates()

    candidate.refresh_from_db()
    assert candidate.status == DuplicateStatus.REJECTED
    assert candidate.canonical is None
    assert candidate.note == 'different floor'
    assert candidate.score == 100  # evidence refreshed, verdict untouched
    assert again.candidates_updated == 1


def test_a_confirmed_link_is_not_undone_by_redetection(places):
    left, right = matching_pair(places)
    services.detect_candidates()
    services.confirm_candidate(
        DuplicateCandidate.objects.get(), canonical=DuplicateCanonical.LEFT
    )

    services.detect_candidates()

    candidate = DuplicateCandidate.objects.get()
    right.refresh_from_db()
    assert candidate.status == DuplicateStatus.CONFIRMED
    assert right.duplicate_of_id == left.pk


def test_rejecting_a_confirmed_candidate_clears_the_pointer(places):
    left, right = matching_pair(places)
    services.detect_candidates()
    candidate = DuplicateCandidate.objects.get()
    services.confirm_candidate(candidate, canonical=DuplicateCanonical.LEFT)

    services.reject_candidate(candidate)

    right.refresh_from_db()
    candidate.refresh_from_db()
    assert right.duplicate_of is None
    assert candidate.canonical is None
    assert candidate.status == DuplicateStatus.REJECTED


def test_dry_run_records_nothing(places):
    matching_pair(places)

    result = services.detect_candidates(dry_run=True)

    assert result.matches == 1
    assert result.candidates_created == 1
    assert DuplicateCandidate.objects.count() == 0


def test_source_city_and_limit_filters_bound_the_run(places):
    matching_pair(places)
    other_city = City.objects.create(
        province=places.province, code='amol', name_fa='آمل', name_en='Amol'
    )
    matching_pair(places, city=other_city)

    assert services.detect_candidates().matches == 2

    one_city = services.detect_candidates(city=places.city)
    assert one_city.matches == 1
    assert one_city.buckets == 1

    only_divar = services.detect_candidates(source='divar')
    assert only_divar.pairs_evaluated == 0

    capped = services.detect_candidates(limit=1)
    assert capped.pairs_evaluated == 0


def test_confirming_repoints_an_existing_link_and_keeps_both_rows(places):
    left, right = matching_pair(places)
    services.detect_candidates()
    candidate = DuplicateCandidate.objects.get()
    third = make_listing(places, source_id='divar-third', source='divar')
    right.duplicate_of = third
    right.save(update_fields=['duplicate_of'])

    services.confirm_candidate(candidate, canonical=DuplicateCanonical.LEFT)

    right.refresh_from_db()
    assert right.duplicate_of_id == left.pk
    assert Listing.objects.count() == 3
