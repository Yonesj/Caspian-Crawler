"""The candidate pair is ordered, unique, and never links a listing to itself."""

import pytest
from django.db import IntegrityError, transaction

from core.dedup.enums import DuplicateStatus
from core.dedup.models import DuplicateCandidate
from core.listings.models import Listing
from core.sources.enums import Source
from tests.listings.helpers import T0, make_listing

pytestmark = pytest.mark.integration


def pair(places):
    left = make_listing(places, source_id='divar-1', last_seen_at=T0)
    right = make_listing(
        places, source_id='sheypoor-1', source=Source.SHEYPOOR, last_seen_at=T0
    )
    return left, right


def test_a_candidate_defaults_to_pending_evidence(places):
    left, right = pair(places)

    candidate = DuplicateCandidate.objects.create(
        left=left, right=right, score=70, signals=[{'name': 'area', 'weight': 40}]
    )

    assert candidate.status == DuplicateStatus.PENDING
    assert candidate.canonical is None
    assert candidate.is_reviewed is False
    assert candidate.reviewed_at is None


def test_the_pair_is_stored_in_one_order(places):
    left, right = pair(places)

    with pytest.raises(IntegrityError), transaction.atomic():
        DuplicateCandidate.objects.create(left=right, right=left, score=70)


def test_the_same_pair_cannot_be_recorded_twice(places):
    left, right = pair(places)
    DuplicateCandidate.objects.create(left=left, right=right, score=70)

    with pytest.raises(IntegrityError), transaction.atomic():
        DuplicateCandidate.objects.create(left=left, right=right, score=70)


def test_a_listing_cannot_be_its_own_duplicate(places):
    listing = make_listing(places)

    with pytest.raises(IntegrityError), transaction.atomic():
        Listing.objects.filter(pk=listing.pk).update(duplicate_of=listing)

    listing.refresh_from_db()
    assert listing.duplicate_of is None
