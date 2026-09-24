"""Read-only data and permissions for the Unfold operations dashboard."""

import json
from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import format_html
from django.utils.translation import gettext as _


def _can_view(request, permission: str) -> bool:
    return request.user.has_perm(permission)


def can_view_crawl_jobs(request):
    return _can_view(request, "crawling.view_crawljob")


def can_view_crawl_schedules(request):
    return _can_view(request, "crawling.view_crawlschedule")


def can_view_crawl_events(request):
    return _can_view(request, "crawling.view_crawljobevent")


def can_view_listings(request):
    return _can_view(request, "listings.view_listing")


def can_view_listing_images(request):
    return _can_view(request, "listings.view_listingimage")


def can_view_listing_events(request):
    return _can_view(request, "listings.view_listingstatusevent")


def can_view_duplicate_candidates(request):
    return _can_view(request, "dedup.view_duplicatecandidate")


def can_view_provinces(request):
    return _can_view(request, "locations.view_province")


def can_view_cities(request):
    return _can_view(request, "locations.view_city")


def can_view_regions(request):
    return _can_view(request, "locations.view_region")


def can_view_source_locations(request):
    return _can_view(request, "locations.view_sourcelocation")


def can_view_location_aliases(request):
    return _can_view(request, "locations.view_locationalias")


def can_view_source_categories(request):
    return _can_view(request, "sources.view_sourcecategory")


def can_view_users(request):
    return _can_view(request, "accounts.view_user")


def can_view_groups(request):
    return _can_view(request, "auth.view_group")


def _admin_list_url(name: str, **filters) -> str:
    url = reverse(name)
    if filters:
        url = f"{url}?{urlencode(filters)}"
    return url


def _card(title, value, description, icon, href, label=None):
    return {
        "title": title,
        "value": value,
        "description": description,
        "icon": icon,
        "href": href,
        "label": label,
    }


def _listing_cards():
    from core.listings.enums import ListingStatus
    from core.listings.models import Listing

    totals = Listing.objects.aggregate(
        active=Count("pk", filter=Q(status=ListingStatus.ACTIVE)),
        stale=Count("pk", filter=Q(status=ListingStatus.STALE)),
        delisted=Count("pk", filter=Q(status=ListingStatus.DELISTED)),
    )
    list_url = "admin:listings_listing_changelist"
    return [
        _card(
            _("Active listings"),
            totals["active"],
            _("Currently available at the source"),
            "check_circle",
            _admin_list_url(list_url, status__exact=ListingStatus.ACTIVE),
            _("Available"),
        ),
        _card(
            _("Stale listings"),
            totals["stale"],
            _("Missing from recent crawl observations"),
            "schedule",
            _admin_list_url(list_url, status__exact=ListingStatus.STALE),
            _("Needs observation"),
        ),
        _card(
            _("Delisted listings"),
            totals["delisted"],
            _("Confirmed unavailable at the source"),
            "remove_circle",
            _admin_list_url(list_url, status__exact=ListingStatus.DELISTED),
            _("Unavailable"),
        ),
    ]


def _job_cards(now):
    from core.crawling.enums import CrawlJobStatus
    from core.crawling.models import CrawlJob

    queued_statuses = [CrawlJobStatus.QUEUED, CrawlJobStatus.RUNNING]
    failed_statuses = [CrawlJobStatus.FAILED, CrawlJobStatus.PARTIALLY_SUCCEEDED]
    issue_cutoff = now - timedelta(hours=24)
    totals = CrawlJob.objects.aggregate(
        in_progress=Count("pk", filter=Q(status__in=queued_statuses)),
        recent_issues=Count(
            "pk",
            filter=Q(
                status__in=failed_statuses,
                finished_at__gte=issue_cutoff,
            ),
        ),
    )
    list_url = "admin:crawling_crawljob_changelist"
    return [
        _card(
            _("Jobs in progress"),
            totals["in_progress"],
            _("Queued or currently running"),
            "pending_actions",
            _admin_list_url(list_url, status__in=",".join(queued_statuses)),
            _("Live queue"),
        ),
        _card(
            _("Crawl issues (24h)"),
            totals["recent_issues"],
            _("Failed or only partially completed"),
            "error",
            _admin_list_url(
                list_url,
                status__in=",".join(failed_statuses),
                finished_at__gte=issue_cutoff.isoformat(),
            ),
            _("Review"),
        ),
    ]


def _duplicate_card():
    from core.dedup.enums import DuplicateStatus
    from core.dedup.models import DuplicateCandidate

    count = DuplicateCandidate.objects.filter(status=DuplicateStatus.PENDING).count()
    return _card(
        _("Pending duplicate reviews"),
        count,
        _("Cross-source matches awaiting a decision"),
        "difference",
        _admin_list_url(
            "admin:dedup_duplicatecandidate_changelist",
            status__exact=DuplicateStatus.PENDING,
        ),
        _("Human review"),
    )


def _job_chart(now):
    from core.crawling.enums import CrawlJobStatus
    from core.crawling.models import CrawlJob

    statuses = (
        CrawlJobStatus.SUCCEEDED,
        CrawlJobStatus.PARTIALLY_SUCCEEDED,
        CrawlJobStatus.FAILED,
    )
    today = timezone.localdate(now)
    days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    start = timezone.make_aware(
        datetime.combine(days[0], time.min), timezone.get_current_timezone()
    )
    raw_counts = (
        CrawlJob.objects.filter(finished_at__gte=start, status__in=statuses)
        .annotate(day=TruncDate("finished_at"))
        .values("day", "status")
        .annotate(total=Count("pk"))
    )
    counts = {(row["day"], row["status"]): row["total"] for row in raw_counts}
    series = {
        status: [counts.get((day, status), 0) for day in days] for status in statuses
    }
    labels = [day.strftime("%m/%d") for day in days]
    data = {
        "labels": labels,
        "datasets": [
            {
                "label": _("Succeeded"),
                "data": series[CrawlJobStatus.SUCCEEDED],
                "borderColor": "#0f766e",
                "backgroundColor": "#0f766e",
                "tension": 0.25,
            },
            {
                "label": _("Partially succeeded"),
                "data": series[CrawlJobStatus.PARTIALLY_SUCCEEDED],
                "borderColor": "#d97706",
                "backgroundColor": "#d97706",
                "borderDash": [6, 4],
                "tension": 0.25,
            },
            {
                "label": _("Failed"),
                "data": series[CrawlJobStatus.FAILED],
                "borderColor": "#dc2626",
                "backgroundColor": "#dc2626",
                "borderDash": [2, 3],
                "tension": 0.25,
            },
        ],
    }
    options = {
        "responsive": True,
        "maintainAspectRatio": False,
        "plugins": {"legend": {"position": "bottom"}},
        "scales": {"y": {"beginAtZero": True, "ticks": {"precision": 0}}},
    }
    table = {
        "headers": [_("Day"), _("Succeeded"), _("Partial"), _("Failed")],
        "rows": [
            [
                label,
                series[CrawlJobStatus.SUCCEEDED][index],
                series[CrawlJobStatus.PARTIALLY_SUCCEEDED][index],
                series[CrawlJobStatus.FAILED][index],
            ]
            for index, label in enumerate(labels)
        ],
    }
    return {
        "data": json.dumps(data),
        "options": json.dumps(options),
        "table": table,
        "has_data": any(sum(values) for values in series.values()),
    }


def _recent_jobs_table():
    from core.crawling.models import CrawlJob

    jobs = CrawlJob.objects.select_related("province", "city", "region")[:8]
    rows = []
    for job in jobs:
        detail_url = reverse("admin:crawling_crawljob_change", args=[job.pk])
        scope = job.region or job.city or job.province
        rows.append(
            [
                format_html(
                    '<a class="font-semibold text-primary-600" href="{}">#{}</a>',
                    detail_url,
                    job.pk,
                ),
                job.get_source_display(),
                str(scope) if scope else "—",
                job.get_status_display(),
                format_html(
                    '<span title="{}">{} / {}</span>',
                    _("created / updated"),
                    job.listings_created,
                    job.listings_updated,
                ),
                date_format(timezone.localtime(job.created_at), "SHORT_DATETIME_FORMAT"),
            ]
        )
    return {
        "headers": [
            _("Job"),
            _("Source"),
            _("Scope"),
            _("Status"),
            _("Created / updated"),
            _("Requested at"),
        ],
        "rows": rows,
    }


def dashboard_callback(request, context):
    """Add only the operational data the current admin user may view."""
    now = timezone.now()
    cards = []

    if can_view_listings(request):
        cards.extend(_listing_cards())
    if can_view_crawl_jobs(request):
        cards.extend(_job_cards(now))
    if can_view_duplicate_candidates(request):
        cards.append(_duplicate_card())

    context.update(
        {
            "dashboard_cards": cards,
            "dashboard_has_widgets": bool(cards),
            "jobs_chart": _job_chart(now) if can_view_crawl_jobs(request) else None,
            "recent_jobs_table": (
                _recent_jobs_table() if can_view_crawl_jobs(request) else None
            ),
        }
    )
    return context
