from decimal import Decimal

from core.normalization.attributes import (
    AREA_KEY_SET,
    DEPOSIT_KEY_SET,
    RENT_KEY_SET,
    SALE_KEY_SET,
    first_value,
    fold_attributes,
    parse_area,
    parse_rooms,
    price_from_attributes,
)

DIVAR_RENT = {
    'متراژ': '۳۰',
    'ساخت': '۱۴۰۴',
    'اتاق': '۱',
    'ودیعه': '\u200f۱۰۰,۰۰۰,۰۰۰ تومان',
    'اجارهٔ ماهانه': '\u200f۱۰,۰۰۰,۰۰۰ تومان',
    'ودیعه و اجاره': 'غیر قابل تبدیل',
}

DIVAR_SALE = {
    'متراژ': '۱۳۶',
    'ساخت': 'قبل از ۱۳۷۰',
    'اتاق': '۳',
    'قیمت کل': '\u200f۶,۹۵۰,۰۰۰,۰۰۰ تومان',
    'قیمت هر متر': '\u200f۵۱,۱۰۲,۰۰۰ تومان',
}


def test_labels_are_matched_through_their_diacritics():
    folded = fold_attributes(DIVAR_RENT)

    assert folded['اجاره ماهانه'] == '\u200f۱۰,۰۰۰,۰۰۰ تومان'
    assert first_value(folded, RENT_KEY_SET) == '\u200f۱۰,۰۰۰,۰۰۰ تومان'


def test_each_money_field_is_read_from_its_own_label():
    folded = fold_attributes(DIVAR_RENT)

    assert price_from_attributes(folded, DEPOSIT_KEY_SET).amount_toman == 100000000
    assert price_from_attributes(folded, RENT_KEY_SET).amount_toman == 10000000
    assert price_from_attributes(folded, SALE_KEY_SET).is_missing


def test_a_per_metre_price_is_not_mistaken_for_the_total():
    folded = fold_attributes(DIVAR_SALE)

    assert price_from_attributes(folded, SALE_KEY_SET).amount_toman == 6950000000


def test_area_reads_persian_digits_and_units():
    assert parse_area('۱۲') == Decimal('12.00')
    assert parse_area('۳۰۰ متر مربع') == Decimal('300.00')
    assert parse_area('قبل از ۱۳۷۰') == Decimal('1370.00')
    assert parse_area('توافقی') is None
    assert parse_area('') is None


def test_rooms_treats_no_room_as_zero():
    assert parse_rooms('۳') == 3
    assert parse_rooms('۴ خواب') == 4
    assert parse_rooms('بدون اتاق') == 0
    assert parse_rooms('') is None
    assert parse_rooms('نامشخص') is None


def test_the_first_known_label_wins():
    folded = fold_attributes({'متراژ': '۹۵۰', 'مساحت': '۱۰۰۰'})

    assert first_value(folded, AREA_KEY_SET) == '۹۵۰'
