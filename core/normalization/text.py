"""Persian text helpers shared by the normalization layer.

Sources write the same word in several ways: Latin and Persian digits, Arabic
``ي``/``ك`` instead of Persian ``ی``/``ک``, optional diacritics (``اجارهٔ`` vs
``اجاره``), and invisible directionality marks between a currency word and its
number.  Two very different jobs need to be kept apart:

* display text (titles, descriptions) only loses the invisible characters and
  the line breaks the sources pad it with — its letters are never rewritten;
* matching keys (attribute names, place names) are folded aggressively so that
  ``اجارهٔ ماهانه`` and ``اجاره ماهانه`` are the same key.

``LocationAlias`` promises that aliases are "stored already folded", and
``fold_lookup`` is that folding.
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹'
ARABIC_INDIC_DIGITS = '٠١٢٣٤٥٦٧٨٩'

DIGIT_TRANSLATION = str.maketrans(
    {
        **{digit: str(index) for index, digit in enumerate(PERSIAN_DIGITS)},
        **{digit: str(index) for index, digit in enumerate(ARABIC_INDIC_DIGITS)},
        '٪': '%',
        '٬': ',',
        '٫': '.',
    }
)

LETTER_TRANSLATION = str.maketrans(
    {
        'ي': 'ی',
        'ى': 'ی',
        'ﻯ': 'ی',
        'ﻰ': 'ی',
        'ك': 'ک',
        'ﻙ': 'ک',
        'ﻚ': 'ک',
        'ة': 'ه',
        'أ': 'ا',
        'إ': 'ا',
        'ٱ': 'ا',
    }
)

# Directionality controls, zero-width joiners and byte-order marks.  They are
# invisible, carry no meaning for matching, and are routinely glued to prices
# ("""\u200f۳۰,۰۰۰,۰۰۰ تومان""").
INVISIBLE = dict.fromkeys(
    map(
        ord,
        '\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e'
        '\u2066\u2067\u2068\u2069\ufeff',
    ),
    None,
)

# Arabic diacritics, including the hamza in "اجارهٔ".
DIACRITICS_RE = re.compile('[\u064b-\u0652\u0654\u0655\u0670]')
WHITESPACE_RE = re.compile(r'\s+')
SEPARATOR_RE = re.compile(r'[،,;|/\\]+')
# Digit-group separators only: a comma that sits between digits and is followed
# by exactly three of them.  The Persian list comma (``،``) is left alone, so
# "از ۸۰، ۱۰۰" still reads as two numbers rather than 80100.
GROUP_SEPARATOR_RE = re.compile(r'(?<=\d)[,\u066c](?=\d{3}(?!\d))')
NUMBER_RE = re.compile(r'\d+(?:\.\d+)?')


def to_ascii_digits(text: str) -> str:
    """Convert Persian/Arabic-Indic digits and separators to ASCII."""
    return (text or '').translate(DIGIT_TRANSLATION)


def strip_invisible(text: str) -> str:
    """Remove directionality controls, ZWNJ and byte-order marks.

    A zero-width non-joiner is dropped rather than turned into a space, because
    ``میشود`` and ``می شود`` are matched through explicit ``LocationAlias`` rows
    instead of by rewriting text the source published.
    """
    return (text or '').translate(INVISIBLE)


def collapse_whitespace(text: str) -> str:
    """Collapse every run of whitespace (including newlines) to one space."""
    return WHITESPACE_RE.sub(' ', text or '').strip()


def clean_display(text: str) -> str:
    """Clean published text without rewriting the words themselves."""
    return collapse_whitespace(strip_invisible(text))


def fold_lookup(text: str) -> str:
    """Fold text into a matching key: digits, letters, diacritics, spacing.

    Deliberately lossy.  ``میشود`` and ``می شود`` fold to the same key, which
    is what place-name and attribute matching needs.
    """
    folded = unicodedata.normalize('NFC', text or '')
    folded = to_ascii_digits(strip_invisible(folded))
    folded = folded.translate(LETTER_TRANSLATION)
    folded = DIACRITICS_RE.sub('', folded)
    return collapse_whitespace(folded)


def numbers(text: str) -> list[Decimal]:
    """Every number in the text, as ``Decimal``, in the order written."""
    cleaned = GROUP_SEPARATOR_RE.sub('', to_ascii_digits(strip_invisible(text or '')))
    found = []
    for match in NUMBER_RE.finditer(cleaned):
        try:
            found.append(Decimal(match.group()))
        except InvalidOperation:  # pragma: no cover - the regex guarantees a number
            continue
    return found


def fragments(text: str) -> list[str]:
    """Split free-text location into parts, most specific part first is *not* implied."""
    return [part for part in (piece.strip() for piece in SEPARATOR_RE.split(text or '')) if part]
