import logging

import pytest

from core.listings.enums import Currency
from core.normalization.money import (
    DEPOSIT,
    RENT,
    SALE,
    field_hint,
    parse_price,
)


def test_persian_price_with_a_direction_mark_is_read():
    value = parse_price('\u200f۳۰,۰۰۰,۰۰۰ تومان')

    assert value.amount_toman == 30000000
    assert value.recognised and not value.is_missing
    assert value.source_currency == Currency.TOMAN


def test_english_digits_and_plain_amounts_work():
    assert parse_price('3100000000 تومان').amount_toman == 3100000000
    assert parse_price('4,500,000 تومان').amount_toman == 4500000


def test_rial_is_converted_to_the_canonical_toman():
    value = parse_price('۱۵,۰۰۰,۰۰۰ ریال')

    assert value.amount_toman == 1500000
    assert value.source_currency == Currency.RIAL


def test_multiplier_words_are_applied():
    assert parse_price('۲ میلیون تومان').amount_toman == 2000000
    assert parse_price('۱.۵ میلیارد تومان').amount_toman == 1500000000
    assert parse_price('۵۰۰ هزار تومان').amount_toman == 500000


def test_a_range_keeps_its_lower_bound():
    assert parse_price('از ۱۰۰ تا ۱۲۰ میلیون تومان').amount_toman == 100000000


def test_negotiable_prices_have_no_amount():
    for raw in ('توافقی', 'پرداخت توافقی', 'قیمت توافقی'):
        value = parse_price(raw)
        assert value.is_negotiable
        assert value.is_missing
        assert value.recognised


def test_a_published_zero_means_not_stated():
    # Divar publishes 0 in its schema.org offer when it has no price to give.
    value = parse_price('۰')

    assert value.is_missing
    assert not value.is_negotiable


def test_absent_price_is_missing_but_recognised():
    for raw in ('', None, '   '):
        value = parse_price(raw)
        assert value.is_missing
        assert value.recognised
        assert not value.is_negotiable


def test_nightly_rates_are_not_written_into_monthly_fields(caplog):
    with caplog.at_level(logging.DEBUG, logger='north_estate.normalize'):
        value = parse_price('۱,۰۰۰,۰۰۰ تومان / شب')

    assert value.is_missing
    assert not value.recognised


def test_unreadable_text_is_reported_rather_than_guessed(caplog):
    with caplog.at_level(logging.WARNING, logger='north_estate.normalize'):
        value = parse_price('به قیمت روز')

    assert value.is_missing
    assert not value.recognised
    assert 'به قیمت روز' in caplog.text


def test_compound_multiplier_expressions_are_refused():
    value = parse_price('۲ میلیارد و ۵۰۰ میلیون تومان')

    assert value.is_missing
    assert not value.recognised


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('اجاره: ۶۰,۰۰۰,۰۰۰ تومان', RENT),
        ('ودیعه: ۳۰,۰۰۰,۰۰۰ تومان', DEPOSIT),
        ('قیمت کل: ۶,۹۵۰,۰۰۰,۰۰۰ تومان', SALE),
        ('۶,۹۵۰,۰۰۰,۰۰۰ تومان', None),
        ('توافقی', None),
    ],
)
def test_field_hint_reads_the_label_the_row_printed(raw, expected):
    assert field_hint(raw) == expected
