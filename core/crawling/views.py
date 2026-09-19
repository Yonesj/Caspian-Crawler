from django.conf import settings
from rest_framework import mixins, viewsets
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core.listings.enums import PropertyType, TransactionType
from core.sources.enums import Source

from .models import CrawlJob
from .serializers import (
    CrawlJobCreateSerializer,
    CrawlJobListSerializer,
    CrawlJobSerializer,
    CrawlOptionsSerializer,
)

if 'drf_spectacular' in settings.INSTALLED_APPS:
    from drf_spectacular.utils import extend_schema
else:
    def extend_schema(**kwargs):
        return lambda view: view


def _choices(values):
    return [{'value': value, 'label': label} for value, label in values]


class CrawlOptionsView(GenericAPIView):
    permission_classes = (AllowAny,)
    serializer_class = CrawlOptionsSerializer

    def get(self, request):
        payload = {
            'sources': _choices(Source.choices),
            'transaction_types': _choices(TransactionType.choices),
            'property_types': _choices(PropertyType.choices),
        }
        return Response(self.get_serializer(payload).data)


class CrawlJobViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = (IsAuthenticated,)
    queryset = CrawlJob.objects.all()

    @extend_schema(
        request=CrawlJobCreateSerializer,
        responses={201: CrawlJobSerializer},
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.action == 'create':
            return CrawlJobCreateSerializer
        if self.action == 'list':
            return CrawlJobListSerializer
        return CrawlJobSerializer

    def get_queryset(self):
        queryset = CrawlJob.objects.select_related(
            'province', 'city', 'region', 'requested_by'
        )
        if self.action == 'retrieve':
            queryset = queryset.prefetch_related('events')
        if not self.request.user.is_authenticated:
            return queryset.none()
        if not self.request.user.is_staff:
            queryset = queryset.filter(requested_by=self.request.user)
        return queryset
