"""Operator entry points for duplicate detection: a command and a task."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.dedup import tasks
from core.dedup.models import DuplicateCandidate
from tests.dedup.helpers import matching_pair

pytestmark = pytest.mark.integration


def test_command_records_and_reports(places, capsys):
    matching_pair(places)

    call_command('detect_duplicate_candidates')

    out = capsys.readouterr().out
    assert DuplicateCandidate.objects.count() == 1
    assert 'recorded 1 match(es)' in out


def test_command_dry_run_writes_nothing(places, capsys):
    matching_pair(places)

    call_command('detect_duplicate_candidates', '--dry-run')

    assert DuplicateCandidate.objects.count() == 0
    assert 'dry run' in capsys.readouterr().out


def test_command_honours_the_city_filter(places):
    matching_pair(places)

    call_command('detect_duplicate_candidates', '--city', places.city.code)

    assert DuplicateCandidate.objects.count() == 1


def test_command_rejects_bad_input(places):
    with pytest.raises(CommandError):
        call_command('detect_duplicate_candidates', '--city', 'nowhere')

    with pytest.raises(CommandError):
        call_command('detect_duplicate_candidates', '--limit', '0')


def test_task_is_inert_until_the_feature_is_enabled(settings, places):
    settings.DEDUP_CANDIDATES_ENABLED = False
    matching_pair(places)

    result = tasks.detect_duplicate_candidates_task()

    assert result == {'skipped': 'disabled'}
    assert DuplicateCandidate.objects.count() == 0


def test_task_detects_when_enabled(settings, places):
    settings.DEDUP_CANDIDATES_ENABLED = True
    matching_pair(places)

    result = tasks.detect_duplicate_candidates_task()

    assert result['candidates_created'] == 1
    assert DuplicateCandidate.objects.count() == 1
