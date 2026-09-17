from decimal import Decimal

from core.normalization.text import (
    clean_display,
    collapse_whitespace,
    fold_lookup,
    fragments,
    numbers,
    strip_invisible,
    to_ascii_digits,
)


def test_persian_and_arabic_digits_become_ascii():
    assert to_ascii_digits('۱۲۳') == '123'
    assert to_ascii_digits('٤٥٦') == '456'
    assert to_ascii_digits('۱۲٫۵') == '12.5'


def test_display_text_is_cleaned_without_rewriting_letters():
    # The directionality mark has to go, but the Persian digits are the source's
    # own text and stay as they were printed.
    assert clean_display('\u200f۳۰,۰۰۰,۰۰۰ تومان') == '۳۰,۰۰۰,۰۰۰ تومان'
    assert clean_display('سلام\n\n  دنیا ') == 'سلام دنیا'


def test_folding_removes_diacritics_and_letter_variants():
    assert fold_lookup('اجارهٔ ماهانه') == 'اجاره ماهانه'
    assert fold_lookup('اجاره ماهانه') == 'اجاره ماهانه'
    assert fold_lookup('بندر انزلى') == 'بندر انزلی'
    assert fold_lookup('كرمان') == 'کرمان'


def test_folding_is_idempotent():
    once = fold_lookup('\u200fاجارهٔ ماهانه (١٢)')

    assert fold_lookup(once) == once


def test_zero_width_joiner_is_dropped_not_spaced():
    assert fold_lookup('می\u200cشود') == 'میشود'


def test_strip_invisible_and_collapse_are_separate_steps():
    assert strip_invisible('\u200eسلام\u200f') == 'سلام'
    assert collapse_whitespace(' a\t b\n c ') == 'a b c'


def test_numbers_reads_grouped_and_decimal_values():
    assert numbers('۶,۹۵۰,۰۰۰,۰۰۰ تومان') == [6950000000]
    assert numbers('۱.۵ میلیارد') == [Decimal('1.5')]
    assert numbers('۱۲') == [12]


def test_numbers_keeps_a_persian_list_comma_as_a_separator():
    assert numbers('از ۸۰، ۱۰۰') == [80, 100]


def test_numbers_returns_nothing_for_words():
    assert numbers('توافقی') == []
    assert numbers('') == []


def test_fragments_splits_free_text_locations():
    assert fragments('مازندران، نوشهر، بندپی') == ['مازندران', 'نوشهر', 'بندپی']
    assert fragments('نوشهر/بندپی') == ['نوشهر', 'بندپی']
    assert fragments('') == []
