from django.contrib import admin

from .models import Listing, ListingImage, ListingStatusEvent


class ListingImageInline(admin.TabularInline):
    model = ListingImage
    extra = 0
    fields = ('position', 'url')


class ListingStatusEventInline(admin.TabularInline):
    model = ListingStatusEvent
    extra = 0
    can_delete = False
    fields = ('from_status', 'to_status', 'reason', 'created_at')
    readonly_fields = ('from_status', 'to_status', 'reason', 'created_at')

    def has_add_permission(self, request, obj=None):
        # Status history is written by the pipeline, not by hand.
        return False


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'title_short', 'source', 'source_id', 'transaction_type',
        'property_type', 'city', 'status', 'last_seen_at',
    )
    list_filter = ('source', 'status', 'transaction_type', 'property_type', 'city__province')
    search_fields = ('title', 'source_id', 'source_url', 'raw_location')
    list_select_related = ('province', 'city', 'region')
    date_hierarchy = 'first_seen_at'
    autocomplete_fields = ('province', 'city', 'region')
    readonly_fields = ('first_seen_at', 'last_seen_at', 'created_at', 'updated_at')
    inlines = (ListingImageInline, ListingStatusEventInline)

    @admin.display(description='Title')
    def title_short(self, obj):
        return obj.title[:80]


@admin.register(ListingImage)
class ListingImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'listing', 'position', 'url')
    search_fields = ('listing__title', 'url')
    list_select_related = ('listing',)


@admin.register(ListingStatusEvent)
class ListingStatusEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'listing', 'from_status', 'to_status', 'reason', 'created_at')
    list_filter = ('to_status',)
    search_fields = ('listing__title', 'reason')
    list_select_related = ('listing',)
