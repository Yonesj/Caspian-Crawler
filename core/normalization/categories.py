"""Source category slugs and titles to the normalised vocabulary.

Sources label their categories with machine-readable slugs (Divar
``apartment-sell``, Sheypoor ``houses-apartments-for-sale``) that already carry
the property type and, for most of them, the transaction.  The rules below are
token-based rather than a per-source lookup table, because both sources spell
the same ideas with the same English words; what varies is which slug a listing
ends up under, and that arrives with the DTO.

Anything the rules cannot read stays honest: an unknown category is ``other``,
and a transaction nobody stated is ``unspecified`` — never a guessed "sale".
"""

from core.listings.enums import PropertyType, TransactionType

REAL_ESTATE_MARKER = 'real-estate'

# Ordered by priority: Sheypoor's "houses-apartments-for-sale" is both, and an
# apartment is the more useful label for a mixed housing category.
PROPERTY_TOKENS = (
    ('apartment', PropertyType.APARTMENT),
    ('apartments', PropertyType.APARTMENT),
    ('suite', PropertyType.APARTMENT),
    ('flat', PropertyType.APARTMENT),
    ('villa', PropertyType.VILLA),
    ('vilas', PropertyType.VILLA),
    ('vila', PropertyType.VILLA),
    ('house', PropertyType.HOUSE),
    ('houses', PropertyType.HOUSE),
    ('home', PropertyType.HOUSE),
    ('garden', PropertyType.GARDEN),
    ('gardens', PropertyType.GARDEN),
    ('land', PropertyType.LAND),
    ('plot', PropertyType.LAND),
    ('rural', PropertyType.RURAL_HOUSE),
    ('village', PropertyType.RURAL_HOUSE),
    ('shop', PropertyType.COMMERCIAL),
    ('store', PropertyType.COMMERCIAL),
    ('office', PropertyType.COMMERCIAL),
    ('commercial', PropertyType.COMMERCIAL),
    ('warehouse', PropertyType.COMMERCIAL),
)
SALE_TOKENS = ('sell', 'sale', 'sold')
RENT_TOKENS = ('rent', 'rents', 'rental')

TITLE_SALE_MARKERS = ('فروش', 'معاوضه', 'واگذاری')
TITLE_RENT_MARKERS = ('اجاره', 'رهن')


def slug_tokens(slug: str) -> tuple[str, ...]:
    return tuple(part for part in slug.replace('_', '-').split('-') if part)


def property_type_from_category(category_path) -> PropertyType:
    """Property type from the source's slugs; ``other`` when nothing matches."""
    tokens = {
        token for slug in category_path or () for token in slug_tokens(str(slug))
    }
    for token, property_type in PROPERTY_TOKENS:
        if token in tokens:
            return property_type
    return PropertyType.OTHER


def transaction_type_from_category(category_path) -> TransactionType | None:
    """Transaction from the slugs, most specific first, or ``None`` if silent."""
    for slug in reversed(tuple(category_path or ())):
        tokens = set(slug_tokens(str(slug)))
        if tokens & set(SALE_TOKENS):
            return TransactionType.SALE
        if tokens & set(RENT_TOKENS):
            return TransactionType.RENT
    return None


def transaction_type_from_title(title: str) -> TransactionType | None:
    """Read the listing's own title when the category does not say.

    A title that mentions both kinds ("فروش یا اجاره") is ambiguous and gets no
    answer rather than a coin flip.
    """
    text = title or ''
    has_sale = any(marker in text for marker in TITLE_SALE_MARKERS)
    has_rent = any(marker in text for marker in TITLE_RENT_MARKERS)
    if has_sale and has_rent:
        return None
    if has_sale:
        return TransactionType.SALE
    if has_rent:
        return TransactionType.RENT
    return None


def classify(category_path, title: str = '') -> tuple[str, str]:
    """Return ``(transaction_type, property_type)`` for one listing."""
    transaction = transaction_type_from_category(category_path)
    if transaction is None:
        transaction = transaction_type_from_title(title)
    return (
        transaction or TransactionType.UNSPECIFIED,
        property_type_from_category(category_path),
    )


def is_real_estate(category_path) -> bool:
    """Whether the source itself filed this listing under property.

    City-wide crawls return jobs, pets and phones; this is how the pipeline can
    tell them apart from a listing whose category simply was not recognised.
    """
    slugs = tuple(str(slug) for slug in category_path or ())
    if any(REAL_ESTATE_MARKER in slug for slug in slugs):
        return True
    return property_type_from_category(slugs) != PropertyType.OTHER
