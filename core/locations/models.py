"""Location reference data.

Cities and regions are **data**, never code: crawler adapters resolve the
source's own place identifiers through :class:`SourceLocation` instead of
hardcoding a city list.  The hierarchy is three levels deep
(``Province -> City -> Region``) because the sources publish listings at
different granularities: sometimes only the province is known, sometimes a
neighbourhood (``منطقه``) is.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.sources.enums import Source


def exactly_one_location_target() -> Q:
    """Return a fresh Q enforcing "point at exactly one hierarchy level".

    Returned as a function (rather than a module constant) so each constraint
    owns its own expression object.
    """
    return (
        Q(province__isnull=False, city__isnull=True, region__isnull=True)
        | Q(province__isnull=True, city__isnull=False, region__isnull=True)
        | Q(province__isnull=True, city__isnull=True, region__isnull=False)
    )


class LocationTargetMixin(models.Model):
    """Validation shared by rows that point at exactly one hierarchy level."""

    class Meta:
        abstract = True

    def clean(self):
        super().clean()

        # The database constraint enforces "exactly one level", so these checks
        # only ever fire for a half-built hierarchy (province + region without
        # the city in between) or a mismatched parent/child pair, both of which
        # deserve a clearer error than an IntegrityError.
        if self.city_id and self.province_id and self.city.province_id != self.province_id:
            raise ValidationError(
                {'city': 'City does not belong to the selected province.'}
            )

        if self.region_id and self.city_id and self.region.city_id != self.city_id:
            raise ValidationError(
                {'region': 'Region does not belong to the selected city.'}
            )

        if self.region_id and self.city_id is None and self.province_id is not None:
            raise ValidationError(
                {'city': 'A region belongs to a city; select the city or drop the province.'}
            )

    def location_target(self):
        """Return the most specific populated level, or ``None``."""
        return self.region or self.city or self.province


class Province(models.Model):
    code = models.SlugField(max_length=64, unique=True)
    name_fa = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120)
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive rows are kept for history but excluded from selection.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name_en']
        verbose_name = 'province'
        verbose_name_plural = 'provinces'

    def __str__(self):
        return self.name_en


class City(models.Model):
    province = models.ForeignKey(
        Province, on_delete=models.PROTECT, related_name='cities'
    )
    code = models.SlugField(max_length=64)
    name_fa = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name_en']
        verbose_name = 'city'
        verbose_name_plural = 'cities'
        constraints = [
            models.UniqueConstraint(
                fields=['province', 'code'], name='city_unique_code_per_province'
            ),
        ]

    def __str__(self):
        return f'{self.name_en} ({self.province.name_en})'


class Region(models.Model):
    """The most specific level currently published by the sources."""

    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name='regions')
    code = models.SlugField(max_length=64)
    name_fa = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name_en']
        verbose_name = 'region'
        verbose_name_plural = 'regions'
        constraints = [
            models.UniqueConstraint(
                fields=['city', 'code'], name='region_unique_code_per_city'
            ),
        ]

    def __str__(self):
        return f'{self.name_en} ({self.city.name_en})'


class SourceLocation(LocationTargetMixin):
    """Maps one source's own place identifier onto the local hierarchy.

    ``external_id`` is whatever the source uses (Divar's numeric place id,
    Sheypoor's slug) and is stable enough to cache; ``raw_label`` keeps the
    human-readable text so mappings can be audited later.
    """

    source = models.CharField(max_length=32, choices=Source.choices)
    external_id = models.CharField(max_length=191)
    raw_label = models.CharField(max_length=255, blank=True, default='')

    province = models.ForeignKey(
        Province,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='source_locations',
    )
    city = models.ForeignKey(
        City,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='source_locations',
    )
    region = models.ForeignKey(
        Region,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='source_locations',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['source', 'external_id']
        verbose_name = 'source location mapping'
        verbose_name_plural = 'source location mappings'
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'external_id'],
                name='source_location_unique_external_id',
            ),
            models.CheckConstraint(
                condition=exactly_one_location_target(),
                name='source_location_exactly_one_target',
            ),
        ]

    def __str__(self):
        label = self.raw_label or self.external_id
        return f'{self.get_source_display()}: {label}'


class LocationAlias(LocationTargetMixin):
    """Normalised free-text place name found in listing text.

    ``alias`` must be stored already folded (whitespace collapsed, Arabic
    ``ي``/``ك`` mapped to Persian ``ی``/``ک``, ZWNJ handled) so that lookups are
    exact matches rather than fuzzy ones; the normalization helper lives in the
    normalization layer.
    """

    alias = models.CharField(max_length=255, unique=True)
    province = models.ForeignKey(
        Province,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='aliases',
    )
    city = models.ForeignKey(
        City,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='aliases',
    )
    region = models.ForeignKey(
        Region,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='aliases',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['alias']
        verbose_name = 'location alias'
        verbose_name_plural = 'location aliases'
        constraints = [
            models.CheckConstraint(
                condition=exactly_one_location_target(),
                name='location_alias_exactly_one_target',
            ),
        ]

    def __str__(self):
        return self.alias
