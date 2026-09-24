from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import SourceCategory


@admin.register(SourceCategory)
class SourceCategoryAdmin(ModelAdmin):
    list_display = ('source', 'transaction_type', 'property_type', 'external_id')
    list_filter = ('source', 'transaction_type', 'property_type')
    search_fields = ('external_id',)
