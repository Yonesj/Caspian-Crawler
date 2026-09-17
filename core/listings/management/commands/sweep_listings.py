"""Operator entry point for the listing lifecycle sweep."""

from django.core.management.base import BaseCommand, CommandError

from core.listings.lifecycle import sweep_listings


class Command(BaseCommand):
    help = (
        'Age listings that finished crawls did not see (active -> stale -> '
        'delisted). Listings are marked, never deleted.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--job-id', type=int, help='Sweep one crawl job only.')
        parser.add_argument(
            '--limit', type=int, help='Sweep at most this many crawl jobs.'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would change without writing anything.',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        if limit is not None and limit < 1:
            raise CommandError('--limit must be at least 1.')

        result = sweep_listings(
            job_id=options['job_id'], limit=limit, dry_run=options['dry_run']
        )

        for skipped in result.skipped:
            self.stdout.write(
                self.style.WARNING(
                    f'skipped job #{skipped["job_id"]}: {skipped["reason"]}'
                )
            )

        prefix = 'dry run: would have swept' if result.dry_run else 'swept'
        self.stdout.write(
            self.style.SUCCESS(
                f'{prefix} {result.jobs_swept} job(s) of '
                f'{result.jobs_considered} considered: '
                f'{result.marked_stale} stale, {result.marked_delisted} delisted, '
                f'{len(result.skipped)} skipped'
            )
        )
