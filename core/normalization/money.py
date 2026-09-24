"""Turning published price text into canonical Toman amounts.

One canonical unit is stored (Toman) and the unit of the stored amount is
recorded on the row, so a price published in Rial is divided by ten and the
original wording is kept in ``raw_data``.  Anything the parser cannot read
becomes "missing" rather than a guess: a price the source does not publish, or
publishes as ``0`` (Divar's way of saying "no price"), is NULL, and a
negotiable price is NULL plus ``is_price_negotiable``.
"""

import logging
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from core.listings.enums import Currency

from .text import collapse_whitespace, fold_lookup, numbers, strip_invisible

logger = logging.getLogger('caspian_crawler.normalize')

SALE = 'sale'
DEPOSIT = 'deposit'
RENT = 'rent'

NEGOTIABLE_MARKERS = ('توافقی', 'مذاکره')
UNIT_FACTORS = (
    ('میلیارد', Decimal(1_000_000_000)),
    ('میلیون', Decimal(1_000_000)),
    ('هزار', Decimal(1_000)),
)
RIAL_WORDS = ('ریال',)
# A nightly rate cannot be stored in the monthly/whole-price columns, so it is
# reported as unreadable instead of being written into the wrong field.
NIGHTLY_RE = re.compile(r'(?:/\s*شب|هر\s*شب|یک\s*شب)')
# Longest marker first, so "ودیعه و اجاره" does not resolve to rent.
FIELD_HINTS = (
    ('ودیعه', DEPOSIT),
    ('رهن', DEPOSIT),
    ('اجاره', RENT),
    ('قیمت', SALE),
)


@dataclass(frozen=True)
class PriceValue:
    """One published price, already converted to the canonical unit.

    ``recognised`` is False when the source printed *something* the parser could
    not read; the caller keeps the raw text and stores no amount.
    """

    amount_toman: Decimal | None = None
    is_negotiable: bool = False
    source_currency: str = Currency.TOMAN
    recognised: bool = True
    raw: str = ''

    @property
    def is_missing(self) -> bool:
        return self.amount_toman is None


def parse_price(raw: str | None) -> PriceValue:
    """Read one price the way a human would, or report it as unreadable."""
    text = collapse_whitespace(strip_invisible(raw or ''))
    if not text:
        return PriceValue(raw=raw or '')

    if any(marker in text for marker in NEGOTIABLE_MARKERS):
        return PriceValue(is_negotiable=True, raw=raw or '')

    if NIGHTLY_RE.search(text):
        logger.debug('price is a nightly rate, not a monthly or total price: %r', raw)
        return PriceValue(recognised=False, raw=raw or '')

    source_currency = (
        Currency.RIAL if any(word in text for word in RIAL_WORDS) else Currency.TOMAN
    )
    amount = _amount(text)
    if amount is None:
        logger.warning('unrecognised price text: %r', raw)
        return PriceValue(
            source_currency=source_currency, recognised=False, raw=raw or ''
        )

    if source_currency == Currency.RIAL:
        amount = amount / 10

    amount = _toman(amount)
    if amount == 0:
        # Sources publish 0 for "no price stated"; stored as missing, not zero.
        return PriceValue(source_currency=source_currency, raw=raw or '')

    return PriceValue(
        amount_toman=amount, source_currency=source_currency, raw=raw or ''
    )


def field_hint(raw: str | None) -> str | None:
    """Which money field a list-row price refers to, when the label says so.

    Divar's list rows write "اجاره: ۶۰,۰۰۰,۰۰۰ تومان" for a rent listing's
    monthly rent; a bare amount on a sale listing is the total price.
    """
    text = fold_lookup(raw or '')
    for marker, field in FIELD_HINTS:
        if fold_lookup(marker) in text:
            return field
    return None


def _amount(text: str) -> Decimal | None:
    values = numbers(text)
    if not values:
        return None
    multipliers = [factor for word, factor in UNIT_FACTORS if word in text]
    if len(multipliers) > 1:
        # "۲ میلیارد و ۵۰۰ میلیون" needs term-by-term arithmetic; rather than
        # risk a wrong number it is reported as unreadable.
        logger.warning('compound price expression is not supported: %r', text)
        return None
    factor = multipliers[0] if multipliers else Decimal(1)
    # A range ("۱۰۰ تا ۱۲۰ میلیون") keeps its lower bound, which is the only
    # value the source states that is true of the whole range.
    return min(values) * factor


def _toman(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)
