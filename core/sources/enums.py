"""Source-agnostic vocabulary shared by the location and listing domains.

This module intentionally holds no models and imports nothing heavy, so
settings, domain models and crawler code can all reference the same values
without pulling the HTTP stack into the Django app registry.
"""

from django.db import models


class Source(models.TextChoices):
    """Public sources the project crawls."""

    DIVAR = "divar", "Divar"
    SHEYPOOR = "sheypoor", "Sheypoor"
