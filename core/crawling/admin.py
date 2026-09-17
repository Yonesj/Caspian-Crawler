from django.contrib import admin, messages

from .enums import CrawlJobStatus
from .models import CrawlJob, CrawlJobEvent, CrawlSchedule


class CrawlJobEventInline(admin.TabularInline):
    model = CrawlJobEvent
    extra = 0
    can_delete = False
    fields = ('from_status', 'to_status', 'level', 'reason', 'message', 'created_at')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        # The lifecycle log is written by the pipeline, never by hand.
        return False


@admin.register(CrawlJob)
class CrawlJobAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'source', 'scope', 'transaction_type', 'property_type',
        'status', 'listings_created', 'listings_updated', 'errors', 'created_at',
    )
    list_filter = ('source', 'status', 'transaction_type', 'property_type')
    search_fields = ('id', 'source_external_id', 'source_category', 'celery_task_id')
    list_select_related = ('province', 'city', 'region')
    readonly_fields = (
        'status', 'source_external_id', 'source_category', 'celery_task_id',
        'pages_fetched', 'stubs_seen', 'details_fetched', 'listings_created',
        'listings_updated', 'listings_skipped', 'listings_out_of_scope', 'errors',
        'report', 'error', 'created_at', 'updated_at', 'queued_at', 'started_at',
        'finished_at',
    )
    inlines = (CrawlJobEventInline,)
    actions = ('requeue_jobs',)

    @admin.display(description='Scope')
    def scope(self, obj):
        return obj.region or obj.city or obj.province or '-'

    @admin.action(description='Re-queue selected jobs')
    def requeue_jobs(self, request, queryset):
        from .tasks import run_crawl_job

        queued = 0
        for job in queryset.exclude(status=CrawlJobStatus.RUNNING):
            run_crawl_job.delay(job.pk)
            queued += 1
        self.message_user(request, f'Queued {queued} job(s).', messages.SUCCESS)


@admin.register(CrawlSchedule)
class CrawlScheduleAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'source', 'scope', 'transaction_type', 'property_type',
        'interval_minutes', 'is_enabled', 'next_run_at', 'last_run_at',
    )
    list_filter = ('source', 'is_enabled', 'transaction_type', 'property_type')
    search_fields = ('name',)
    list_select_related = ('province', 'city', 'region')

    @admin.display(description='Scope')
    def scope(self, obj):
        return obj.region or obj.city or obj.province or '-'


@admin.register(CrawlJobEvent)
class CrawlJobEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'job', 'from_status', 'to_status', 'level', 'created_at')
    list_filter = ('level', 'to_status')
    search_fields = ('job__id', 'reason', 'message')
    list_select_related = ('job',)
