import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.locations.models import (
    City,
    LocationAlias,
    Province,
    Region,
    SourceLocation,
)
from core.sources.enums import Source

pytestmark = pytest.mark.integration

DATA_PATH = 'core/locations/data/locations.json'


def seed(*args):
    out = StringIO()
    call_command('seed_locations', *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def packaged_counts():
    with open(DATA_PATH, encoding='utf-8') as handle:
        payload = json.load(handle)

    return {
        'provinces': len(payload['provinces']),
        'cities': sum(len(p['cities']) for p in payload['provinces']),
        'regions': sum(
            len(city.get('regions', []))
            for province in payload['provinces']
            for city in province['cities']
        ),
    }


def test_seed_creates_the_catalog_from_the_packaged_file(db, packaged_counts):
    seed()

    assert Province.objects.count() == packaged_counts['provinces']
    assert City.objects.count() == packaged_counts['cities']
    assert Region.objects.count() == packaged_counts['regions']

    mazandaran = Province.objects.get(code='mazandaran')
    assert mazandaran.name_fa == 'مازندران'
    assert City.objects.get(province=mazandaran, code='sari').name_en == 'Sari'
    assert Region.objects.filter(city__province=mazandaran).exists()

    # Region-level data is intentionally curated, not exhaustive.
    assert Region.objects.count() < City.objects.count()


def test_seed_is_idempotent(db):
    seed()
    snapshot = (
        Province.objects.count(),
        City.objects.count(),
        Region.objects.count(),
        LocationAlias.objects.count(),
        SourceLocation.objects.count(),
    )

    seed()

    assert snapshot == (
        Province.objects.count(),
        City.objects.count(),
        Region.objects.count(),
        LocationAlias.objects.count(),
        SourceLocation.objects.count(),
    )


def test_seed_records_aliases_for_each_level(db):
    seed()

    heshmat = LocationAlias.objects.get(alias='هشتپر')
    assert heshmat.city.code == 'talesh'

    province_alias = LocationAlias.objects.get(alias='گیلان')
    assert province_alias.province.code == 'gilan'


def test_seed_dry_run_writes_nothing(db):
    output = seed('--dry-run')

    assert Province.objects.count() == 0
    assert City.objects.count() == 0
    assert 'Would seed' in output


def test_seed_rejects_a_file_without_provinces(db, tmp_path):
    broken = tmp_path / 'locations.json'
    broken.write_text(json.dumps({'provinces': []}), encoding='utf-8')

    with pytest.raises(CommandError):
        seed('--path', str(broken))


def test_seed_reports_a_missing_file(db, tmp_path):
    with pytest.raises(CommandError):
        seed('--path', str(tmp_path / 'nope.json'))


def test_seed_maps_each_source_id_onto_its_own_level(db):
    seed()

    assert SourceLocation.objects.get(
        source=Source.DIVAR, external_id='22'
    ).city == City.objects.get(code='sari')
    assert SourceLocation.objects.get(
        source=Source.SHEYPOOR, external_id='mazandaran'
    ).province == Province.objects.get(code='mazandaran')
    assert SourceLocation.objects.get(
        source=Source.SHEYPOOR, external_id='band-e-pey'
    ).region == Region.objects.get(code='band-e-pey')


def test_seed_reports_source_location_counts(db):
    assert 'source_locations=' in seed('--dry-run')


def _write(tmp_path, province_extra):
    path = tmp_path / 'locations.json'
    province = {
        'code': 'mazandaran',
        'name_fa': 'مازندران',
        'name_en': 'Mazandaran',
        'cities': [],
        **province_extra,
    }
    path.write_text(json.dumps({'provinces': [province]}), encoding='utf-8')
    return str(path)


def test_seed_rejects_an_unknown_source_name(db, tmp_path):
    path = _write(tmp_path, {'source_ids': {'kijiji': '1'}})

    with pytest.raises(CommandError, match='unknown source'):
        seed('--path', path)


def test_seed_rejects_an_empty_source_id(db, tmp_path):
    path = _write(tmp_path, {'source_ids': {'divar': '  '}})

    with pytest.raises(CommandError, match='must not be empty'):
        seed('--path', path)


def test_seed_rejects_a_source_id_used_twice(db, tmp_path):
    path = _write(
        tmp_path,
        {
            'source_ids': {'divar': '22'},
            'cities': [
                {'code': 'sari', 'name_fa': 'ساری', 'name_en': 'Sari', 'source_ids': {'divar': '22'}}
            ],
        },
    )

    with pytest.raises(CommandError, match='already used'):
        seed('--path', path)


def test_seed_moves_a_mapping_instead_of_duplicating_it(db, tmp_path):
    seed('--path', _write(tmp_path, {'source_ids': {'divar': '22'}}))
    assert SourceLocation.objects.get(source='divar', external_id='22').province is not None

    moved = tmp_path / 'moved.json'
    moved.write_text(
        json.dumps(
            {
                'provinces': [
                    {
                        'code': 'mazandaran',
                        'name_fa': 'مازندران',
                        'name_en': 'Mazandaran',
                        'cities': [
                            {
                                'code': 'sari',
                                'name_fa': 'ساری',
                                'name_en': 'Sari',
                                'source_ids': {'divar': '22'},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding='utf-8',
    )
    seed('--path', str(moved))

    mappings = SourceLocation.objects.filter(source='divar', external_id='22')
    assert mappings.count() == 1
    assert mappings.get().city.code == 'sari'
