from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ReadOnlyModelViewSet

from .enums import ListingStatus
from .filters import ListingFilter
from .models import Listing
from .serializers import ListingSerializer


class ListingViewSet(ReadOnlyModelViewSet):
    serializer_class = ListingSerializer
    permission_classes = (AllowAny,)
    filterset_class = ListingFilter
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    search_fields = ('title', 'description')
    ordering_fields = (
        'published_at',
        'first_seen_at',
        'last_seen_at',
        'area_sqm',
        'sale_price',
        'deposit',
        'monthly_rent',
    )
    ordering = ('-first_seen_at', '-id')

    def get_queryset(self):
        queryset = Listing.objects.select_related(
            'province', 'city', 'region'
        ).prefetch_related('images')
        user = self.request.user
        requested_status = self.request.query_params.get('status')
        staff_detail = user.is_authenticated and user.is_staff and self.action == 'retrieve'
        staff_filtered_list = (
            user.is_authenticated and user.is_staff and bool(requested_status)
        )
        if not staff_detail and not staff_filtered_list:
            queryset = queryset.filter(status=ListingStatus.ACTIVE)
        return queryset
