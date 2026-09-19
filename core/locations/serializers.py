from rest_framework import serializers

from .models import City, Province, Region


class ProvinceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Province
        fields = ('id', 'code', 'name_fa', 'name_en')


class CitySerializer(serializers.ModelSerializer):
    class Meta:
        model = City
        fields = ('id', 'province', 'code', 'name_fa', 'name_en')


class RegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Region
        fields = ('id', 'city', 'code', 'name_fa', 'name_en')
