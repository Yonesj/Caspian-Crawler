from django.contrib import admin

from .models import SourceCategory


@admin.register(SourceCategory)
class SourceCategoryAdmin(admin.ModelAdmin):
    list_display = ('source', 'transaction_type', 'property_type', 'external_id')
    list_filter = ('source', 'transaction_type', 'property_type')
    search_fields = ('external_id',)
