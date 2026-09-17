from datetime import UTC, datetime

from core.normalization.dates import TEHRAN, parse_published_at


def test_divar_jalali_wall_clock_is_read_as_tehran_time():
    # "انتشار آگهی: ۲۶ شهریور ۱۴۰۵، ۲۳:۰۷" — 26 Shahrivar 1405 is 2026-09-17.
    parsed = parse_published_at('انتشار آگهی: ۲۶ شهریور ۱۴۰۵، ۲۳:۰۷')

    assert parsed == datetime(2026, 9, 17, 19, 37, tzinfo=UTC)
    assert parsed.astimezone(TEHRAN).hour == 23


def test_sheypoor_naive_stamp_is_local_not_utc():
    # Verified against the live site: this value tracks Tehran wall-clock.
    parsed = parse_published_at('2026-06-16 16:34:12.9812')

    assert parsed == datetime(2026, 6, 16, 13, 4, 12, 981200, tzinfo=UTC)


def test_iso_values_keep_their_own_offset():
    assert parse_published_at('2026-09-17T19:02:24.352990Z') == datetime(
        2026, 9, 17, 19, 2, 24, 352990, tzinfo=UTC
    )
    assert parse_published_at('2026-09-17T22:32:24+03:30') == datetime(
        2026, 9, 17, 19, 2, 24, tzinfo=UTC
    )


def test_date_without_a_time_is_the_start_of_the_day_in_tehran():
    parsed = parse_published_at('۲۶ شهریور ۱۴۰۵')

    assert parsed == datetime(2026, 9, 16, 20, 30, tzinfo=UTC)


def test_esfand_30_exists_only_in_a_leap_jalali_year():
    # Stored in UTC, so the calendar date has to be read back in Tehran time.
    leap_day = parse_published_at('۳۰ اسفند ۱۴۰۳')

    assert leap_day.astimezone(TEHRAN).date().isoformat() == '2025-03-20'
    assert parse_published_at('۳۱ اسفند ۱۴۰۴') is None


def test_unreadable_stamps_return_none():
    for raw in (None, '', '   ', 'به تازگی', '2026-13-45 99:99'):
        assert parse_published_at(raw) is None
