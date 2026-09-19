from rest_framework.generics import ListAPIView
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny

from .models import City, Province, Region
from .serializers import CitySerializer, ProvinceSerializer, RegionSerializer


def _optional_id(request, name):
    value = request.query_params.get(name)
    if not value:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: 'Must be a positive integer.'}) from exc
    if parsed < 1:
        raise ValidationError({name: 'Must be a positive integer.'})
    return parsed


class SelectorListView(ListAPIView):
    """Small unpaginated reference lists used to build crawl selectors."""

    permission_classes = (AllowAny,)
    pagination_class = None


class ProvinceListView(SelectorListView):
    serializer_class = ProvinceSerializer
    queryset = Province.objects.filter(is_active=True).order_by('name_en', 'id')


class CityListView(SelectorListView):
    serializer_class = CitySerializer

    def get_queryset(self):
        queryset = City.objects.filter(is_active=True).order_by('name_en', 'id')
        province_id = _optional_id(self.request, 'province')
        if province_id is not None:
            queryset = queryset.filter(province_id=province_id)
        return queryset


class RegionListView(SelectorListView):
    serializer_class = RegionSerializer

    def get_queryset(self):
        queryset = Region.objects.filter(is_active=True).order_by('name_en', 'id')
        city_id = _optional_id(self.request, 'city')
        if city_id is not None:
            queryset = queryset.filter(city_id=city_id)
        return queryset
