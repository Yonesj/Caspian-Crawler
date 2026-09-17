import dataclasses

import pytest
from django.test import override_settings

from core.crawling import scope as scope_module
from core.crawling.errors import ScopeResolutionError
from core.locations.models import SourceLocation
from core.sources.config import DEFAULT_POLICIES
from core.sources.enums import Source
from core.sources.errors import SourceDisabled

pytestmark = pytest.mark.integration


def test_region_scope_uses_the_most_specific_mapping(job_factory):
    job = job_factory(target='region')

    scope = scope_module.build_scope(job)

    assert scope.external_id == '22-99'


def test_city_scope_falls_back_to_the_province_when_unmapped(job_factory, places):
    job = job_factory(target='city')
    SourceLocation.objects.filter(
        source=Source.DIVAR, external_id='22'
    ).delete()

    scope = scope_module.build_scope(job)

    assert scope.external_id == '893'


def test_province_scope_resolves_directly(job_factory):
    job = job_factory(target='province')

    assert scope_module.build_scope(job).external_id == '893'


def test_unmapped_place_raises_before_any_request(job_factory, places):
    job = job_factory(target='city')
    SourceLocation.objects.filter(source=Source.DIVAR).delete()

    with pytest.raises(ScopeResolutionError):
        scope_module.build_scope(job)


def test_disabled_source_cannot_be_scoped(job_factory):
    job = job_factory()
    policy = DEFAULT_POLICIES['divar']
    disabled = {'divar': dataclasses.replace(policy, enabled=False)}

    with override_settings(CRAWL_POLICIES=disabled), pytest.raises(SourceDisabled):
        scope_module.build_scope(job)


def test_explicit_category_overrides_the_mapping(job_factory):
    job = job_factory(source_category='explicit-slug')

    assert scope_module.build_scope(job).category == 'explicit-slug'


def test_unmapped_property_selection_leaves_the_category_empty(job_factory):
    job = job_factory(property_type='house')

    scope = scope_module.build_scope(job)

    assert job.source_category == ''
    assert scope.category is None


def test_page_limit_is_carried_into_the_scope(job_factory):
    job = job_factory(page_limit=3)

    assert scope_module.build_scope(job).page_limit == 3
