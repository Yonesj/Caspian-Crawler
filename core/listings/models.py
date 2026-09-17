"""Normalized listing domain.

A :class:`Listing` is the *source-independent* representation the API exposes.
Source-specific payloads are kept in ``raw_data`` for debugging and re-parsing,
but nothing outside the adapter layer should read them.

Money is stored in a single canonical unit (Toman) together with an explicit
currency column; a missing price is ``NULL`` — never ``0`` — and negotiable
prices carry a flag instead of a fake number.
"""

from django.db import models

from core.locations.models import City, Province, Region
from core.sources.enums import Source

from .enums import Currency, ListingStatus, PropertyType, TransactionType


class Listing(models.Model):
    # Identity -----------------------------------------------------------------
    # (source, source_id) is the listing identity, deliberately *not* the URL:
    # sources rewrite URLs and the same listing can be reached through many of
    # them.  ``source_id`` is the id the source itself uses in its own API.
    source = models.CharField(max_length=32, choices=Source.choices)
    source_id = models.CharField(max_length=191)
    source_url = models.URLField(max_length=500)

    # Presentation -------------------------------------------------------------
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, default='')

    # Classification -----------------------------------------------------------
    transaction_type = models.CharField(
        max_length=16, choices=TransactionType.choices
    )
    property_type = models.CharField(
        max_length=32, choices=PropertyType.choices, default=PropertyType.OTHER
    )

    # Location (nullable: a listing may arrive with only a raw label) ----------
    province = models.ForeignKey(
        Province, null=True, blank=True, on_delete=models.PROTECT,
        related_name='listings',
    )
    city = models.ForeignKey(
        City, null=True, blank=True, on_delete=models.PROTECT,
        related_name='listings',
    )
    region = models.ForeignKey(
        Region, null=True, blank=True, on_delete=models.PROTECT,
        related_name='listings',
    )
    raw_location = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Location text as published by the source, before normalization.',
    )

    # Price --------------------------------------------------------------------
    sale_price = models.DecimalField(
        max_digits=16, decimal_places=0, null=True, blank=True,
        help_text='Total price for sale listings, in Toman.',
    )
    deposit = models.DecimalField(
        max_digits=16, decimal_places=0, null=True, blank=True,
        help_text='Deposit (ودیعه) for rent listings, in Toman.',
    )
    monthly_rent = models.DecimalField(
        max_digits=16, decimal_places=0, null=True, blank=True,
        help_text='Monthly rent (اجاره ماهانه) for rent listings, in Toman.',
    )
    price_currency = models.CharField(
        max_length=3, choices=Currency.choices, default=Currency.TOMAN
    )
    is_price_negotiable = models.BooleanField(
        default=False,
        help_text='Source published a negotiable/unspecified price (توافقی).',
    )

    # Physical attributes ------------------------------------------------------
    area_sqm = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    rooms = models.PositiveSmallIntegerField(null=True, blank=True)

    # Lifecycle ----------------------------------------------------------------
    status = models.CharField(
        max_length=16, choices=ListingStatus.choices, default=ListingStatus.ACTIVE
    )
    published_at = models.DateTimeField(
        null=True, blank=True, help_text='Publication time reported by the source.'
    )
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    # Provenance ---------------------------------------------------------------
    raw_data = models.JSONField(
        default=dict, blank=True,
        help_text='Last payload received from the source, kept for diagnostics.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-first_seen_at', '-id']
        verbose_name = 'listing'
        verbose_name_plural = 'listings'
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'source_id'], name='listing_unique_source_identity'
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(sale_price__isnull=True) | models.Q(sale_price__gte=0)
                )
                & (models.Q(deposit__isnull=True) | models.Q(deposit__gte=0))
                & (models.Q(monthly_rent__isnull=True) | models.Q(monthly_rent__gte=0))
                & (models.Q(area_sqm__isnull=True) | models.Q(area_sqm__gte=0)),
                name='listing_no_negative_amounts',
            ),
        ]
        indexes = [
            models.Index(fields=['source', 'status'], name='listing_source_status_idx'),
            models.Index(fields=['city', 'status'], name='listing_city_status_idx'),
            models.Index(
                fields=['transaction_type', 'property_type'], name='listing_kind_idx'
            ),
            models.Index(fields=['-published_at'], name='listing_published_idx'),
        ]

    def __str__(self):
        return f'[{self.get_source_display()}:{self.source_id}] {self.title[:60]}'

    # Convenience ---------------------------------------------------------------
    @property
    def location_target(self):
        """Most specific populated location level, or ``None``."""
        return self.region or self.city or self.province

    @property
    def is_available(self):
        return self.status == ListingStatus.ACTIVE


class ListingImage(models.Model):
    listing = models.ForeignKey(
        Listing, on_delete=models.CASCADE, related_name='images'
    )
    url = models.URLField(max_length=1000)
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', 'id']
        verbose_name = 'listing image'
        verbose_name_plural = 'listing images'
        constraints = [
            models.UniqueConstraint(
                fields=['listing', 'position'],
                name='listing_image_unique_position',
            ),
        ]

    def __str__(self):
        return f'{self.listing_id}#{self.position}'


class ListingStatusEvent(models.Model):
    """Append-only log of availability transitions.

    A listing that disappears from a crawl is never deleted silently; the
    pipeline records the transition here so availability over time stays
    auditable.
    """

    listing = models.ForeignKey(
        Listing, on_delete=models.CASCADE, related_name='status_events'
    )
    from_status = models.CharField(
        max_length=16, choices=ListingStatus.choices, blank=True, default=''
    )
    to_status = models.CharField(max_length=16, choices=ListingStatus.choices)
    reason = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'listing status event'
        verbose_name_plural = 'listing status events'

    def __str__(self):
        return f'{self.listing_id}: {self.from_status or "-"} -> {self.to_status}'
