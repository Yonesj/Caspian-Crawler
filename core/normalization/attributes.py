"""Source attribute fields to typed values.

Divar and Sheypoor both publish a ``{label: value}`` block on the detail page,
with Persian labels and Persian digits (``متراژ``/``۱۲``, ``ودیعه``/
``\u200f۳۰,۰۰۰,۰۰۰ تومان``).  Only labels that are exactly known are read: a
value the source did not publish stays NULL instead of being guessed from the
title or the description.
"""

from decimal import ROUND_HALF_UP, Decimal

from .money import PriceValue, parse_price
from .text import fold_lookup, numbers

AREA_KEYS = ('متراژ', 'متراژ زمین', 'متراژ ویلا', 'متراژ ملک', 'مساحت', 'مساحت زمین')
ROOMS_KEYS = ('اتاق', 'تعداد اتاق', 'خواب', 'تعداد خواب')
SALE_KEYS = ('قیمت کل', 'قیمت فروش', 'قیمت')
DEPOSIT_KEYS = ('ودیعه', 'رهن کامل', 'رهن')
RENT_KEYS = ('اجاره ماهانه', 'اجاره')

# Folded at import time, so "اجارهٔ ماهانه" and "اجاره ماهانه" are the same key.
AREA_KEY_SET = {fold_lookup(key) for key in AREA_KEYS}
ROOMS_KEY_SET = {fold_lookup(key) for key in ROOMS_KEYS}
SALE_KEY_SET = {fold_lookup(key) for key in SALE_KEYS}
DEPOSIT_KEY_SET = {fold_lookup(key) for key in DEPOSIT_KEYS}
RENT_KEY_SET = {fold_lookup(key) for key in RENT_KEYS}


def fold_attributes(attributes: dict[str, str] | None) -> dict[str, str]:
    """Index an attribute block by folded label, first write wins."""
    folded: dict[str, str] = {}
    for label, value in (attributes or {}).items():
        key = fold_lookup(str(label))
        if key and key not in folded:
            folded[key] = str(value)
    return folded


def first_value(folded, keys) -> str | None:
    for key in folded:
        if key in keys:
            return folded[key]
    return None


def parse_area(raw: str | None) -> Decimal | None:
    """Square metres from an area attribute; ``None`` when it is not numeric."""
    found = numbers(raw or '')
    if not found:
        return None
    return min(found).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def parse_rooms(raw: str | None) -> int | None:
    """"بدون اتاق" is zero rooms (a studio), not "unknown"."""
    text = fold_lookup(raw or '')
    if not text:
        return None
    if 'بدون' in text:
        return 0
    found = numbers(text)
    if not found:
        return None
    return int(found[0])


def price_from_attributes(folded: dict[str, str], keys) -> PriceValue:
    return parse_price(first_value(folded, keys))
