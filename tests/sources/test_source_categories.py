import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.listings.enums import PropertyType, TransactionType
from core.sources.categories import resolve_category
from core.sources.models import SourceCategory

pytestmark = pytest.mark.integration


def test_resolver_returns_the_seeded_slug(db):
    SourceCategory.objects.create(
        source='divar',
        transaction_type=TransactionType.SALE,
        property_type=PropertyType.APARTMENT,
        external_id='apartment-sell',
    )

    assert (
        resolve_category('divar', TransactionType.SALE, PropertyType.APARTMENT)
        == 'apartment-sell'
    )


def test_resolver_returns_none_for_an_unmapped_selection(db):
    # No row: the caller must crawl without a category filter rather than guess.
    assert resolve_category('divar', 'sale', 'villa') is None


def test_resolver_returns_none_for_an_unknown_source(db):
    assert resolve_category('nope', 'sale', 'apartment') is None


def test_seed_command_is_idempotent(db):
    call_command('seed_source_categories')
    first = SourceCategory.objects.count()
    call_command('seed_source_categories')

    assert first > 0
    assert SourceCategory.objects.count() == first
    assert SourceCategory.objects.filter(external_id='apartment-sell').exists()


def test_seed_command_rejects_an_unknown_source(db, tmp_path):
    path = tmp_path / 'categories.json'
    path.write_text(json.dumps({'nope': []}), encoding='utf-8')

    with pytest.raises(CommandError):
        call_command('seed_source_categories', path=str(path))


def test_seed_command_rejects_an_unknown_property_type(db, tmp_path):
    path = tmp_path / 'categories.json'
    path.write_text(
        json.dumps({'divar': [{'transaction_type': 'sale', 'property_type': 'spaceship', 'external_id': 'x'}]}),
        encoding='utf-8',
    )

    with pytest.raises(CommandError):
        call_command('seed_source_categories', path=str(path))


def test_seed_command_dry_run_writes_nothing(db, tmp_path):
    path = tmp_path / 'categories.json'
    path.write_text(
        json.dumps({'divar': [{'transaction_type': 'sale', 'property_type': 'villa', 'external_id': 'villa-sell'}]}),
        encoding='utf-8',
    )

    call_command('seed_source_categories', path=str(path), dry_run=True)

    assert not SourceCategory.objects.exists()
