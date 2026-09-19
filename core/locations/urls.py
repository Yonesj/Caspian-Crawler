from django.urls import path

from .views import CityListView, ProvinceListView, RegionListView

app_name = 'locations'

urlpatterns = [
    path('provinces/', ProvinceListView.as_view(), name='province-list'),
    path('cities/', CityListView.as_view(), name='city-list'),
    path('regions/', RegionListView.as_view(), name='region-list'),
]
