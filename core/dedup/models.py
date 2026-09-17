"""Cross-source duplicate candidates.

A candidate records that two listings on *different* sources look like the same
property.  It is evidence for a human, never an automatic decision: detection
writes ``pending`` rows, and only a reviewer's confirmation sets the
``Listing.duplicate_of`` pointer.  Nothing is merged, rewritten or deleted --
the loser keeps all of its data and its status history.
"""

from django.conf import settings
from django.db import models

from core.listings.models import Listing

from .enums import DuplicateCanonical, DuplicateStatus


class DuplicateCandidate(models.Model):
    # The pair is stored ordered (``left_id < right_id``) so that "the same two
    # listings" can never produce two rows and the unique constraint holds.
    left = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name='duplicate_candidates_as_left',
    )
    right = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name='duplicate_candidates_as_right',
    )

    status = models.CharField(
        max_length=16, choices=DuplicateStatus.choices, default=DuplicateStatus.PENDING
    )
    canonical = models.CharField(
        max_length=8,
        choices=DuplicateCanonical.choices,
        null=True,
        blank=True,
        help_text='Which side a reviewer decided to keep (confirmed candidates only).',
    )
    score = models.PositiveSmallIntegerField(
        help_text='Weighted evidence at detection time, 0-100.'
    )
    signals = models.JSONField(
        default=list,
        blank=True,
        help_text='The individual signals that produced the score.',
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='duplicate_reviews',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-score', '-id']
        verbose_name = 'duplicate candidate'
        verbose_name_plural = 'duplicate candidates'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(left__lt=models.F('right')),
                name='duplicate_candidate_ordered_pair',
            ),
            models.UniqueConstraint(
                fields=['left', 'right'], name='duplicate_candidate_unique_pair'
            ),
        ]
        indexes = [
            models.Index(fields=['status', '-score'], name='dedup_status_score_idx'),
        ]

    def __str__(self):
        return f'#{self.pk} {self.left_id}~{self.right_id} ({self.status})'

    @property
    def is_reviewed(self) -> bool:
        return self.status != DuplicateStatus.PENDING
