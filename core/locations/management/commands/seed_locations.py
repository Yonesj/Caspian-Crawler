"""Load the curated province/city/region reference data.

The command is idempotent: re-running it updates names, aliases and source
identifiers in place and never duplicates rows, so it is safe to call from a
deployment entrypoint.  Rows are never deleted, because listings reference them
(``PROTECT``) and removing a city would either fail or silently orphan history.

Each level may carry ``source_ids`` -- the identifiers the sources themselves
use for that place (Divar's numeric city id, Sheypoor's slug) -- which become
``SourceLocation`` rows.  That is what lets crawler code resolve a place without
containing a city list.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.locations.models import (
    City,
    LocationAlias,
    Province,
    Region,
    SourceLocation,
)
from core.sources.enums import Source

DEFAULT_DATA_PATH = Path(__file__).resolve().parents[2] / 'data' / 'locations.json'

LEVELS = ('provinces', 'cities', 'regions', 'aliases', 'source_locations')


class Command(BaseCommand):
    help = 'Idempotently seed provinces, cities, regions and location aliases.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--path',
            default=str(DEFAULT_DATA_PATH),
            help='Path to the locations JSON file (defaults to the packaged data file).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate and report without writing anything.',
        )

    def handle(self, *args, **options):
        path = Path(options['path'])
        provinces = self._validate(self._load(path))

        self.created = dict.fromkeys(LEVELS, 0)
        self.updated = dict.fromkeys(LEVELS, 0)

        with transaction.atomic():
            for province_data in provinces:
                self._upsert_province(province_data)
            if options['dry_run']:
                transaction.set_rollback(True)

        prefix = 'Would seed' if options['dry_run'] else 'Seeded'
        summary = ', '.join(
            f'{level}={self.created[level]} new/{self.updated[level]} updated'
            for level in LEVELS
        )
        self.stdout.write(self.style.SUCCESS(f'{prefix} {summary} ({path})'))

    # -- loading/validation ---------------------------------------------------
    def _load(self, path):
        try:
            with path.open(encoding='utf-8') as handle:
                return json.load(handle)
        except FileNotFoundError:
            raise CommandError(f'Locations file not found: {path}')
        except json.JSONDecodeError as exc:
            raise CommandError(f'Locations file is not valid JSON: {exc}')

    def _validate(self, payload):
        provinces = payload.get('provinces')
        if not isinstance(provinces, list) or not provinces:
            raise CommandError('Locations file must contain a non-empty "provinces" list.')

        seen_source_ids: set[tuple[str, str]] = set()
        seen_province_codes = set()
        for province in provinces:
            code = province.get('code')
            if not code:
                raise CommandError('Every province needs a "code".')
            if code in seen_province_codes:
                raise CommandError(f'Duplicate province code in file: {code}')
            seen_province_codes.add(code)
            self._check_source_ids(province, f'Province {code}', seen_source_ids)

            seen_city_codes = set()
            for city in province.get('cities', []):
                city_code = city.get('code')
                if not city_code:
                    raise CommandError(f'Province {code}: every city needs a "code".')
                if city_code in seen_city_codes:
                    raise CommandError(f'Province {code}: duplicate city code {city_code}')
                seen_city_codes.add(city_code)
                self._check_source_ids(city, f'City {city_code}', seen_source_ids)

                seen_region_codes = set()
                for region in city.get('regions', []):
                    region_code = region.get('code')
                    if not region_code:
                        raise CommandError(
                            f'City {city_code}: every region needs a "code".'
                        )
                    if region_code in seen_region_codes:
                        raise CommandError(
                            f'City {city_code}: duplicate region code {region_code}'
                        )
                    seen_region_codes.add(region_code)
                    self._check_source_ids(
                        region, f'Region {region_code}', seen_source_ids
                    )

        return provinces

    def _check_source_ids(self, node, label, seen):
        source_ids = node.get('source_ids') or {}
        if not isinstance(source_ids, dict):
            raise CommandError(f'{label}: "source_ids" must be an object.')
        for source, external_id in source_ids.items():
            if str(source) not in Source.values:
                raise CommandError(f'{label}: unknown source {source!r} in "source_ids".')
            if not str(external_id).strip():
                raise CommandError(f'{label}: "source_ids" for {source} must not be empty.')
            key = (str(source), str(external_id))
            if key in seen:
                raise CommandError(
                    f'{label}: {source} id {external_id!r} is already used by another place.'
                )
            seen.add(key)

    # -- upserts --------------------------------------------------------------
    def _track(self, level, created):
        bucket = self.created if created else self.updated
        bucket[level] += 1

    def _upsert_province(self, data):
        province, created = Province.objects.update_or_create(
            code=data['code'],
            defaults={'name_fa': data['name_fa'], 'name_en': data['name_en']},
        )
        self._track('provinces', created)
        self._upsert_aliases(data.get('aliases'), province=province)
        self._upsert_source_ids(data.get('source_ids'), province=province)

        for city_data in data.get('cities', []):
            city, created = City.objects.update_or_create(
                province=province,
                code=city_data['code'],
                defaults={
                    'name_fa': city_data['name_fa'],
                    'name_en': city_data['name_en'],
                },
            )
            self._track('cities', created)
            self._upsert_aliases(city_data.get('aliases'), city=city)
            self._upsert_source_ids(city_data.get('source_ids'), city=city)

            for region_data in city_data.get('regions', []):
                region, created = Region.objects.update_or_create(
                    city=city,
                    code=region_data['code'],
                    defaults={
                        'name_fa': region_data['name_fa'],
                        'name_en': region_data['name_en'],
                    },
                )
                self._track('regions', created)
                self._upsert_aliases(region_data.get('aliases'), region=region)
                self._upsert_source_ids(region_data.get('source_ids'), region=region)

    def _upsert_source_ids(self, source_ids, **target):
        if not source_ids:
            return
        # Clear the other levels: a place may have moved up or down the
        # hierarchy since the last run, and a mapping points at exactly one.
        defaults = {'province': None, 'city': None, 'region': None, **target}
        for source, external_id in source_ids.items():
            _, created = SourceLocation.objects.update_or_create(
                source=str(source),
                external_id=str(external_id),
                defaults=defaults,
            )
            self._track('source_locations', created)

    def _upsert_aliases(self, aliases, **target):
        if not aliases:
            return
        # Clear the other levels: the alias target may have moved between
        # hierarchy levels since the last run, and the model allows exactly one.
        defaults = {'province': None, 'city': None, 'region': None, **target}
        for alias in aliases:
            _, created = LocationAlias.objects.update_or_create(
                alias=alias.strip(), defaults=defaults
            )
            self._track('aliases', created)
