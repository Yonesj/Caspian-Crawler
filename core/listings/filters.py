from django_filters import rest_framework as filters

from .models import Listing


class ListingFilter(filters.FilterSet):
    min_area = filters.NumberFilter(field_name='area_sqm', lookup_expr='gte')
    max_area = filters.NumberFilter(field_name='area_sqm', lookup_expr='lte')
    min_sale_price = filters.NumberFilter(field_name='sale_price', lookup_expr='gte')
    max_sale_price = filters.NumberFilter(field_name='sale_price', lookup_expr='lte')
    min_deposit = filters.NumberFilter(field_name='deposit', lookup_expr='gte')
    max_deposit = filters.NumberFilter(field_name='deposit', lookup_expr='lte')
    min_monthly_rent = filters.NumberFilter(
        field_name='monthly_rent', lookup_expr='gte'
    )
    max_monthly_rent = filters.NumberFilter(
        field_name='monthly_rent', lookup_expr='lte'
    )

    class Meta:
        model = Listing
        fields = (
            'source',
            'transaction_type',
            'property_type',
            'province',
            'city',
            'region',
            'status',
            'is_price_negotiable',
        )
