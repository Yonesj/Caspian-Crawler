"""Load the verified source category mappings.

Idempotent: re-running updates slugs in place and never duplicates rows.  Each
mapping must name a known source and a known transaction/property pair, so a
typo in the data file fails loudly instead of creating an unreachable mapping.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.listings.enums import PropertyType, TransactionType
from core.sources.enums import Source
from core.sources.models import SourceCategory

DEFAULT_DATA_PATH = Path(__file__).resolve().parents[2] / 'data' / 'categories.json'


class Command(BaseCommand):
    help = 'Idempotently seed the source category slug mappings.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--path',
            default=str(DEFAULT_DATA_PATH),
            help='Path to the categories JSON file (defaults to the packaged data file).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate and report without writing anything.',
        )

    def handle(self, *args, **options):
        path = Path(options['path'])
        entries = self._validate(self._load(path))

        created = updated = 0
        with transaction.atomic():
            for source, entry in entries:
                _, was_created = SourceCategory.objects.update_or_create(
                    source=source,
                    transaction_type=entry['transaction_type'],
                    property_type=entry['property_type'],
                    defaults={'external_id': entry['external_id']},
                )
                created += was_created
                updated += not was_created
            if options['dry_run']:
                transaction.set_rollback(True)

        prefix = 'Would seed' if options['dry_run'] else 'Seeded'
        self.stdout.write(
            self.style.SUCCESS(
                f'{prefix} {created} new/{updated} updated source categories ({path})'
            )
        )

    def _load(self, path):
        try:
            with path.open(encoding='utf-8') as handle:
                return json.load(handle)
        except FileNotFoundError:
            raise CommandError(f'Categories file not found: {path}')
        except json.JSONDecodeError as exc:
            raise CommandError(f'Categories file is not valid JSON: {exc}')

    def _validate(self, payload):
        if not isinstance(payload, dict) or not payload:
            raise CommandError('Categories file must be a non-empty object of source -> list.')

        entries = []
        seen = set()
        for source, mappings in payload.items():
            if str(source) not in Source.values:
                raise CommandError(f'Unknown source {source!r} in categories file.')
            if not isinstance(mappings, list):
                raise CommandError(f'Source {source!r} must map to a list of categories.')
            for mapping in mappings:
                transaction_type = mapping.get('transaction_type')
                property_type = mapping.get('property_type')
                external_id = str(mapping.get('external_id') or '').strip()
                if transaction_type not in TransactionType.values:
                    raise CommandError(
                        f'{source}: unknown transaction_type {transaction_type!r}.'
                    )
                if property_type not in PropertyType.values:
                    raise CommandError(f'{source}: unknown property_type {property_type!r}.')
                if not external_id:
                    raise CommandError(f'{source}: external_id must not be empty.')
                key = (str(source), transaction_type, property_type)
                if key in seen:
                    raise CommandError(f'Duplicate mapping in file: {key}.')
                seen.add(key)
                entries.append((str(source), mapping))
        return entries
