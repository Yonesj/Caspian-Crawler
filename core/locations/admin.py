from django.contrib import admin

from .models import City, LocationAlias, Province, Region, SourceLocation


@admin.register(Province)
class ProvinceAdmin(admin.ModelAdmin):
    list_display = ('name_en', 'name_fa', 'code', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name_en', 'name_fa')
    prepopulated_fields = {'code': ('name_en',)}


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ('name_en', 'name_fa', 'province', 'code', 'is_active')
    list_filter = ('is_active', 'province')
    search_fields = ('code', 'name_en', 'name_fa', 'province__name_en')
    list_select_related = ('province',)


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ('name_en', 'name_fa', 'city', 'code', 'is_active')
    list_filter = ('is_active', 'city__province')
    search_fields = ('code', 'name_en', 'name_fa', 'city__name_en')
    list_select_related = ('city', 'city__province')


@admin.register(SourceLocation)
class SourceLocationAdmin(admin.ModelAdmin):
    list_display = ('source', 'external_id', 'raw_label', 'resolved_target')
    list_filter = ('source',)
    search_fields = ('external_id', 'raw_label')
    list_select_related = ('province', 'city', 'region')

    @admin.display(description='Resolves to')
    def resolved_target(self, obj):
        return obj.location_target() or '—'


@admin.register(LocationAlias)
class LocationAliasAdmin(admin.ModelAdmin):
    list_display = ('alias', 'resolved_target')
    search_fields = ('alias',)
    list_select_related = ('province', 'city', 'region')

    @admin.display(description='Resolves to')
    def resolved_target(self, obj):
        return obj.location_target() or '—'
