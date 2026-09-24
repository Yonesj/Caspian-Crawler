"""Integration coverage for the Unfold operations admin."""

import json

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from django.utils import timezone
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from config.admin_dashboard import dashboard_callback
from core.accounts.admin import GroupAdmin, UserAdmin
from core.crawling.enums import CrawlJobStatus
from core.dedup.models import DuplicateCandidate
from core.listings.enums import ListingStatus
from tests.listings.helpers import make_listing

pytestmark = pytest.mark.integration


def test_auth_models_use_unfold_admin_and_forms():
    user_admin = admin.site._registry[get_user_model()]
    group_admin = admin.site._registry[Group]

    assert isinstance(user_admin, UserAdmin)
    assert isinstance(user_admin, ModelAdmin)
    assert user_admin.form is UserChangeForm
    assert user_admin.add_form is UserCreationForm
    assert user_admin.change_password_form is AdminPasswordChangeForm
    assert isinstance(group_admin, GroupAdmin)
    assert isinstance(group_admin, ModelAdmin)


def test_admin_dashboard_and_representative_model_pages_render(admin_client, job_factory):
    job = job_factory()

    responses = [
        admin_client.get(reverse("admin:index")),
        admin_client.get(reverse("admin:crawling_crawljob_changelist")),
        admin_client.get(reverse("admin:crawling_crawljob_change", args=[job.pk])),
    ]

    assert all(response.status_code == 200 for response in responses)
    dashboard = responses[0].content.decode()
    assert "CaspianCrawler" in dashboard
    assert 'action="/i18n/setlang/"' in dashboard
    assert 'name="language"' in dashboard


def test_dashboard_reports_counts_chart_and_recent_jobs(
    rf, django_user_model, places, job_factory
):
    now = timezone.now()
    user = django_user_model.objects.create_superuser(
        username="dashboard-admin", password="password"
    )
    active = make_listing(places, source_id="dashboard-active")
    stale = make_listing(
        places, source_id="dashboard-stale", status=ListingStatus.STALE
    )
    make_listing(
        places, source_id="dashboard-delisted", status=ListingStatus.DELISTED
    )
    DuplicateCandidate.objects.create(left=active, right=stale, score=72)

    queued = job_factory()
    succeeded = job_factory()
    failed = job_factory()
    queued.status = CrawlJobStatus.QUEUED
    queued.save(update_fields=["status", "updated_at"])
    succeeded.status = CrawlJobStatus.SUCCEEDED
    succeeded.finished_at = now
    succeeded.save(update_fields=["status", "finished_at", "updated_at"])
    failed.status = CrawlJobStatus.FAILED
    failed.finished_at = now
    failed.save(update_fields=["status", "finished_at", "updated_at"])

    request = rf.get(reverse("admin:index"))
    request.user = user
    context = dashboard_callback(request, {})

    cards = {card["icon"]: card["value"] for card in context["dashboard_cards"]}
    assert cards["check_circle"] == 1
    assert cards["schedule"] == 1
    assert cards["remove_circle"] == 1
    assert cards["pending_actions"] == 1
    assert cards["error"] == 1
    assert cards["difference"] == 1

    chart = json.loads(context["jobs_chart"]["data"])
    assert len(chart["labels"]) == 7
    assert sum(chart["datasets"][0]["data"]) == 1
    assert sum(chart["datasets"][2]["data"]) == 1
    assert len(context["recent_jobs_table"]["rows"]) == 3


def test_dashboard_does_not_query_models_without_view_permission(
    db, rf, django_user_model, mocker
):
    user = django_user_model.objects.create_user(username="listing-viewer", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="view_listing"))
    request = rf.get(reverse("admin:index"))
    request.user = user

    job_cards = mocker.patch(
        "config.admin_dashboard._job_cards", side_effect=AssertionError("job query")
    )
    job_chart = mocker.patch(
        "config.admin_dashboard._job_chart", side_effect=AssertionError("chart query")
    )
    recent_jobs = mocker.patch(
        "config.admin_dashboard._recent_jobs_table",
        side_effect=AssertionError("recent-job query"),
    )
    duplicates = mocker.patch(
        "config.admin_dashboard._duplicate_card",
        side_effect=AssertionError("duplicate query"),
    )

    context = dashboard_callback(request, {})

    assert len(context["dashboard_cards"]) == 3
    assert context["jobs_chart"] is None
    assert context["recent_jobs_table"] is None
    job_cards.assert_not_called()
    job_chart.assert_not_called()
    recent_jobs.assert_not_called()
    duplicates.assert_not_called()
