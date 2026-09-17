"""Source-agnostic vocabulary shared by the location and listing domains.

This module intentionally holds no models.  Crawl adapters (added in a later
milestone) live in this package too, so that "which sources exist" is defined
in exactly one place instead of being duplicated as string literals.
"""

from django.db import models


class Source(models.TextChoices):
    """Public sources the project crawls."""

    DIVAR = "divar", "Divar"
    SHEYPOOR = "sheypoor", "Sheypoor"
