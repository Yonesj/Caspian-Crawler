"""Resolve a local (transaction, property) selection to a source category slug.

Deliberately returns ``None`` when no verified mapping exists instead of
guessing: the caller then crawls the place without a category filter, which is
honest about what the source can express, and the job records the limitation.
"""

from .models import SourceCategory


def resolve_category(source: str, transaction_type: str, property_type: str) -> str | None:
    """The source's own category slug, or ``None`` when unmapped."""
    row = SourceCategory.objects.filter(
        source=str(source),
        transaction_type=str(transaction_type),
        property_type=str(property_type),
    ).first()
    return row.external_id if row is not None else None
