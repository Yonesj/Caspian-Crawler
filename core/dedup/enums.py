"""Duplicate-candidate vocabulary.

A candidate is a *suspicion*, not a fact: ``pending`` rows are hints for a human
reviewer, and only ``confirmed`` rows link one listing to another.
"""

from django.db import models


class DuplicateStatus(models.TextChoices):
    PENDING = "pending", "Awaiting review"
    CONFIRMED = "confirmed", "Confirmed duplicate"
    REJECTED = "rejected", "Rejected by a reviewer"


class DuplicateCanonical(models.TextChoices):
    """Which side of a confirmed candidate is the listing worth keeping."""

    LEFT = "left", "Keep the first listing"
    RIGHT = "right", "Keep the second listing"
