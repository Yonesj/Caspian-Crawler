from django.contrib import admin, messages

from .models import DuplicateCandidate


@admin.register(DuplicateCandidate)
class DuplicateCandidateAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'left_id', 'right_id', 'score', 'signals_display', 'status',
        'canonical', 'reviewed_by', 'reviewed_at',
    )
    list_filter = ('status', 'canonical', 'left__source', 'right__source')
    search_fields = (
        'left__title', 'right__title', 'left__source_id', 'right__source_id',
    )
    list_select_related = ('left', 'right', 'reviewed_by')
    readonly_fields = (
        'left', 'right', 'score', 'signals', 'signals_display', 'status', 'canonical',
        'reviewed_by', 'reviewed_at', 'note', 'created_at', 'updated_at',
    )
    actions = ('confirm_keeping_left', 'confirm_keeping_right', 'reject_candidates')

    @admin.display(description='Signals')
    def signals_display(self, obj):
        return ', '.join(
            f'{signal["name"]} {signal["weight"]}' for signal in obj.signals or []
        ) or '-'

    @admin.action(description='Confirm duplicate: keep the first (left) listing')
    def confirm_keeping_left(self, request, queryset):
        self._confirm(request, queryset, canonical='left')

    @admin.action(description='Confirm duplicate: keep the second (right) listing')
    def confirm_keeping_right(self, request, queryset):
        self._confirm(request, queryset, canonical='right')

    def _confirm(self, request, queryset, *, canonical):
        from .services import confirm_candidate

        done = 0
        for candidate in queryset:
            confirm_candidate(candidate, canonical=canonical, reviewed_by=request.user)
            done += 1
        self.message_user(
            request,
            f'Confirmed {done} duplicate candidate(s); the other listing now '
            f'points at the one kept. Nothing was merged or deleted.',
            messages.SUCCESS,
        )

    @admin.action(description='Reject: not the same listing')
    def reject_candidates(self, request, queryset):
        from .services import reject_candidate

        done = 0
        for candidate in queryset:
            reject_candidate(candidate, reviewed_by=request.user)
            done += 1
        self.message_user(
            request, f'Rejected {done} duplicate candidate(s).', messages.SUCCESS
        )
