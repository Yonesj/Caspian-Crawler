"""Operator entry point for duplicate-candidate detection."""

from django.core.management.base import BaseCommand, CommandError

from core.dedup.services import detect_candidates
from core.locations.models import City
from core.sources.enums import Source


class Command(BaseCommand):
    help = (
        'Record cross-source duplicate candidates for human review. '
        'Candidates are hints: nothing is merged, hidden or deleted.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--source', choices=Source.values, help='Limit to one source.')
        parser.add_argument('--city', help='City code, e.g. sari.')
        parser.add_argument(
            '--limit',
            type=int,
            help='Compare at most this many listings per (transaction, city).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be recorded without writing anything.',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        if limit is not None and limit < 1:
            raise CommandError('--limit must be at least 1.')

        result = detect_candidates(
            source=options['source'],
            city=_city(options.get('city')),
            limit=limit,
            dry_run=options['dry_run'],
        )

        prefix = 'dry run: would record' if result.dry_run else 'recorded'
        self.stdout.write(
            self.style.SUCCESS(
                f'{prefix} {result.matches} match(es) from '
                f'{result.pairs_evaluated} pair(s) in {result.buckets} bucket(s): '
                f'{result.candidates_created} new, {result.candidates_updated} refreshed'
            )
        )


def _city(code):
    if not code:
        return None
    city = City.objects.filter(code=code).first()
    if city is None:
        raise CommandError(f'No city with code {code!r}.')
    return city
