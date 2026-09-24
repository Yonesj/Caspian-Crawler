"""Published timestamps to timezone-aware UTC.

Both sources print wall-clock time in Tehran: Divar in Jalali
(``انتشار آگهی: ۲۶ شهریور ۱۴۰۵، ۲۳:۰۷``) and Sheypoor as a naive Gregorian
stamp (``2026-06-16 16:34:12.9812``, verified against the live site to be local
rather than UTC).  Converting here means nothing downstream has to know either.
"""

import logging
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import jdatetime

from .text import collapse_whitespace, strip_invisible, to_ascii_digits

logger = logging.getLogger('caspian_crawler.normalize')

TEHRAN = ZoneInfo('Asia/Tehran')

PERSIAN_MONTHS = {
    'فروردین': 1,
    'اردیبهشت': 2,
    'خرداد': 3,
    'تیر': 4,
    'مرداد': 5,
    'امرداد': 5,
    'شهریور': 6,
    'مهر': 7,
    'آبان': 8,
    'آذر': 9,
    'دی': 10,
    'بهمن': 11,
    'اسفند': 12,
}

JALALI_RE = re.compile(
    r'(?P<day>\d{1,2})\s+(?P<month>[^\s\d,،]+)\s+(?P<year>\d{4})'
    r'(?:\s*[،,]\s*(?P<hour>\d{1,2}):(?P<minute>\d{2}))?'
)
ISO_RE = re.compile(
    r'\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?'
    r'(?:Z|[+-]\d{2}:?\d{2})?'
)


def parse_published_at(raw: str | None, *, default_tz: ZoneInfo = TEHRAN) -> datetime | None:
    """Parse a publication stamp, or return ``None`` if it is not datable."""
    if not raw:
        return None
    text = to_ascii_digits(collapse_whitespace(strip_invisible(raw)))
    if not text:
        return None

    jalali = JALALI_RE.search(text)
    if jalali:
        month = PERSIAN_MONTHS.get(jalali.group('month'))
        if month is not None:
            value = _jalali(
                int(jalali.group('year')),
                month,
                int(jalali.group('day')),
                int(jalali.group('hour') or 0),
                int(jalali.group('minute') or 0),
            )
            if value is not None:
                return _aware(value, default_tz)

    candidate = ISO_RE.search(text)
    if candidate:
        try:
            return _aware(datetime.fromisoformat(candidate.group(0)), default_tz)
        except ValueError:
            pass

    logger.debug('unrecognised publication date: %r', raw)
    return None


def _jalali(year: int, month: int, day: int, hour: int, minute: int):
    try:
        return jdatetime.datetime(year, month, day, hour, minute).togregorian()
    except ValueError:
        logger.debug('impossible Jalali date: %s-%s-%s', year, month, day)
        return None


def _aware(value: datetime, default_tz: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=default_tz)
    return value.astimezone(UTC)
