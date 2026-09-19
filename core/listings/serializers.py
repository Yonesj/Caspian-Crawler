from rest_framework import serializers

from .models import Listing


class LocationReferenceSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    code = serializers.CharField(read_only=True)
    name_fa = serializers.CharField(read_only=True)
    name_en = serializers.CharField(read_only=True)


class ListingLocationSerializer(serializers.Serializer):
    province = LocationReferenceSerializer(allow_null=True, read_only=True)
    city = LocationReferenceSerializer(allow_null=True, read_only=True)
    region = LocationReferenceSerializer(allow_null=True, read_only=True)


class ListingPriceSerializer(serializers.Serializer):
    sale = serializers.DecimalField(
        source='sale_price', max_digits=16, decimal_places=0, allow_null=True,
        read_only=True,
    )
    deposit = serializers.DecimalField(
        max_digits=16, decimal_places=0, allow_null=True, read_only=True
    )
    monthly_rent = serializers.DecimalField(
        max_digits=16, decimal_places=0, allow_null=True, read_only=True
    )
    currency = serializers.CharField(source='price_currency', read_only=True)
    negotiable = serializers.BooleanField(
        source='is_price_negotiable', read_only=True
    )


class ListingSerializer(serializers.ModelSerializer):
    location = ListingLocationSerializer(source='*', read_only=True)
    prices = ListingPriceSerializer(source='*', read_only=True)
    images = serializers.SlugRelatedField(many=True, read_only=True, slug_field='url')

    class Meta:
        model = Listing
        fields = (
            'id',
            'source',
            'source_id',
            'source_url',
            'title',
            'description',
            'transaction_type',
            'property_type',
            'location',
            'prices',
            'area_sqm',
            'rooms',
            'status',
            'published_at',
            'first_seen_at',
            'last_seen_at',
            'last_checked_at',
            'images',
        )
