"""Pure duplicate matching over :class:`ListingFingerprint` values.

The matcher knows nothing about the database, the network or the clock: it takes
two value objects and returns the evidence that they might be the same property
advertised on two sources.  That is what makes the highest-risk logic in the
project -- "are these the same listing?" -- testable without fixtures.

A pair only becomes a candidate if it survives the blockers *and* collects at
least two weighted signals with a score of 50/100.  Nothing here links, merges
or deletes a listing; the caller records a candidate for a human to review.
"""

import re
from dataclasses import asdict, dataclass
from datetime import timedelta

from core.listings.enums import ListingStatus, PropertyType, TransactionType
from core.normalization.text import fold_lookup

# Statuses worth comparing: a hidden row is a local decision and a delisted one
# has already been judged unavailable.
COMPARABLE_STATUSES = (ListingStatus.ACTIVE, ListingStatus.STALE)

# Persian function words: present in almost every title, so they add no evidence.
PERSIAN_STOPWORDS = frozenset(
    {
        'و', 'در', 'با', 'به', 'از', 'برای', 'این', 'آن', 'که', 'را', 'تا',
        'بر', 'یا', 'هم', 'یک', 'های', 'ها', 'ای', 'می', 'شده', 'نیست',
        'هست', 'دارد', 'دارای', 'هر', 'همه', 'نیز', 'ولی', 'اما', 'کنار',
        'داخل', 'روی', 'بین',
    }
)
TOKEN_SEPARATOR_RE = re.compile(r'[^\w]+', re.UNICODE)


@dataclass(frozen=True)
class DedupPolicy:
    """Weights and tolerances of the matcher.

    The defaults are deliberately conservative: two strong signals are required
    before a pair is even offered for review, because a false-positive merge
    costs much more than a missed duplicate.
    """

    area_weight: int = 40
    price_weight: int = 30
    title_weight: int = 20
    published_weight: int = 10
    area_tolerance_sqm: float = 3.0
    area_tolerance_ratio: float = 0.05
    price_tolerance_ratio: float = 0.05
    title_min_jaccard: float = 0.5
    published_window_days: int = 3
    min_signals: int = 2
    min_score: int = 50


@dataclass(frozen=True)
class ListingFingerprint:
    """The comparable surface of a listing, free of model and source detail."""

    listing_id: int
    source: str
    transaction_type: str
    property_type: str
    province_id: int | None
    city_id: int | None
    title: str
    area_sqm: float | None
    price: float | None
    published_at: object | None
    status: str = ListingStatus.ACTIVE
    duplicate_of_id: int | None = None


@dataclass(frozen=True)
class DuplicateSignal:
    name: str
    weight: int
    detail: str


@dataclass(frozen=True)
class DuplicateMatch:
    score: int
    signals: tuple[DuplicateSignal, ...]

    def as_dict(self) -> dict:
        return {
            'score': self.score,
            'signals': [asdict(signal) for signal in self.signals],
        }


def blockers(left, right) -> list[str]:
    """Hard reasons this pair can never be a duplicate, in a stable order."""
    reasons = []
    if left.listing_id == right.listing_id or left.source == right.source:
        # Same-source repeats are the persistence layer's job, not dedup's.
        reasons.append('same_source')
    if left.duplicate_of_id or right.duplicate_of_id:
        reasons.append('already_linked')
    if left.status not in COMPARABLE_STATUSES or right.status not in COMPARABLE_STATUSES:
        reasons.append('not_available')
    if _both_specified_and_different(
        left.transaction_type, right.transaction_type, TransactionType.UNSPECIFIED
    ):
        reasons.append('transaction_mismatch')
    if _both_specified_and_different(
        left.property_type, right.property_type, PropertyType.OTHER
    ):
        reasons.append('property_mismatch')
    if left.city_id and right.city_id and left.city_id != right.city_id:
        reasons.append('city_mismatch')
    if left.province_id and right.province_id and left.province_id != right.province_id:
        reasons.append('province_mismatch')
    return reasons


def signals(left, right, policy=None) -> tuple[DuplicateSignal, ...]:
    """Every weighted signal the pair carries, strongest first."""
    policy = policy or DedupPolicy()
    found = []

    if _areas_agree(left.area_sqm, right.area_sqm, policy):
        found.append(
            DuplicateSignal(
                name='area',
                weight=policy.area_weight,
                detail=f'{left.area_sqm:g} vs {right.area_sqm:g} sqm',
            )
        )

    if _prices_agree(left.price, right.price, policy):
        found.append(
            DuplicateSignal(
                name='price',
                weight=policy.price_weight,
                detail=f'{left.price:g} vs {right.price:g}',
            )
        )

    jaccard = title_jaccard(left.title, right.title)
    if jaccard >= policy.title_min_jaccard:
        found.append(
            DuplicateSignal(
                name='title',
                weight=max(1, round(policy.title_weight * jaccard)),
                detail=f'jaccard={jaccard:.2f}',
            )
        )

    if _publications_are_close(left.published_at, right.published_at, policy):
        found.append(
            DuplicateSignal(
                name='published',
                weight=policy.published_weight,
                detail=f'{left.published_at} vs {right.published_at}',
            )
        )

    return tuple(found)


def match_pair(left, right, policy=None) -> DuplicateMatch | None:
    """The pair's candidacy, or ``None`` when it is too weak or blocked."""
    policy = policy or DedupPolicy()
    if blockers(left, right):
        return None
    found = signals(left, right, policy)
    score = sum(signal.weight for signal in found)
    if len(found) < policy.min_signals or score < policy.min_score:
        return None
    return DuplicateMatch(score=score, signals=found)


def title_tokens(title: str) -> frozenset[str]:
    """Folded, digit-normalised title tokens with Persian stopwords removed."""
    folded = fold_lookup(title or '').lower()
    return frozenset(
        token
        for token in TOKEN_SEPARATOR_RE.split(folded)
        if token and token not in PERSIAN_STOPWORDS
    )


def title_jaccard(left: str, right: str) -> float:
    """Token-set Jaccard similarity; ``0.0`` when either title is unusable."""
    left_tokens = title_tokens(left)
    right_tokens = title_tokens(right)
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


# -- internals ----------------------------------------------------------------

def _both_specified_and_different(left, right, unspecified) -> bool:
    if left == unspecified or right == unspecified:
        return False
    return left != right


def _areas_agree(left, right, policy) -> bool:
    if left is None or right is None:
        return False
    tolerance = max(
        policy.area_tolerance_sqm, policy.area_tolerance_ratio * max(left, right)
    )
    return abs(left - right) <= tolerance


def _prices_agree(left, right, policy) -> bool:
    if not left or not right:  # zero is "not published" by project rule
        return False
    return abs(left - right) <= policy.price_tolerance_ratio * max(left, right)


def _publications_are_close(left, right, policy) -> bool:
    if left is None or right is None:
        return False
    return abs(left - right) <= timedelta(days=policy.published_window_days)
