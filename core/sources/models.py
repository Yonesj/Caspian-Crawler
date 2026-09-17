"""Reference data owned by the source layer.

Adapters speak each source's own vocabulary.  The one piece of that vocabulary
that operators select against -- the category slug a search endpoint expects --
is stored here as data rather than hardcoded in crawler code, so adding a
mapping (or a whole new source) is an insert.

Only slugs that have been verified against a captured fixture or a live check
belong in the seed file.  A missing mapping is a supported state: the crawl
runs place-wide and the job records that it could not narrow by category.
"""

from django.db import models

from core.listings.enums import PropertyType, TransactionType

from .enums import Source


class SourceCategory(models.Model):
    """Maps (transaction, property) onto a source's own category slug.

    ``external_id`` is whatever the source's search endpoint expects (Divar's
    ``apartment-sell``); it is never shown to API consumers.
    """

    source = models.CharField(max_length=32, choices=Source.choices)
    transaction_type = models.CharField(
        max_length=16, choices=TransactionType.choices
    )
    property_type = models.CharField(max_length=32, choices=PropertyType.choices)
    external_id = models.CharField(max_length=191)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['source', 'transaction_type', 'property_type']
        verbose_name = 'source category'
        verbose_name_plural = 'source categories'
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'transaction_type', 'property_type'],
                name='source_category_unique_mapping',
            ),
        ]

    def __str__(self):
        return f'{self.source}: {self.transaction_type}/{self.property_type} -> {self.external_id}'
