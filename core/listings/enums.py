"""Normalized vocabulary shared by listings, adapters and the API.

Adapters translate each source's own wording (``خرید``, ``اجاره``, ``آپارتمان``)
into these values in the normalization layer; nothing downstream should ever
branch on source-specific text.
"""

from django.db import models


class TransactionType(models.TextChoices):
    SALE = "sale", "Sale / purchase"
    RENT = "rent", "Rent"
    # Sources return categories that say nothing about sale vs rent (Sheypoor's
    # bare "land"), and city-wide crawls return listings that are not property
    # at all.  "Unspecified" records that honestly instead of guessing "sale".
    UNSPECIFIED = "unspecified", "Not stated by the source"


class PropertyType(models.TextChoices):
    APARTMENT = "apartment", "Apartment"
    HOUSE = "house", "House"
    VILLA = "villa", "Villa"
    LAND = "land", "Land"
    GARDEN = "garden", "Garden"
    RURAL_HOUSE = "rural_house", "Rural house"
    COMMERCIAL = "commercial", "Commercial / shop"
    OTHER = "other", "Other"


class ListingStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    STALE = "stale", "Not seen in a recent crawl"
    DELISTED = "delisted", "Removed or disabled at the source"
    HIDDEN = "hidden", "Hidden locally"


class Currency(models.TextChoices):
    TOMAN = "IRT", "Iranian Toman"
    RIAL = "IRR", "Iranian Rial"
