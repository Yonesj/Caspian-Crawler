"""Run pending crawl jobs inline.

This is the development escape hatch for a machine without a running Celery
worker: it claims jobs with the same atomic query the worker uses, so running it
alongside workers can never process a job twice.
"""

from django.core.management.base import BaseCommand, CommandError

from core.crawling.enums import CrawlJobStatus
from core.crawling.models import CrawlJob, claim_job
from core.crawling.tasks import execute_job


class Command(BaseCommand):
    help = 'Claim and run pending crawl jobs in the current process.'

    def add_arguments(self, parser):
        parser.add_argument('--job-id', type=int, help='Run one specific job.')
        parser.add_argument(
            '--limit', type=int, default=10, help='Maximum jobs to run (default 10).'
        )

    def handle(self, *args, **options):
        if options['job_id']:
            job_ids = list(
                CrawlJob.objects.filter(pk=options['job_id']).values_list('pk', flat=True)
            )
            if not job_ids:
                raise CommandError(f'No crawl job with id {options["job_id"]}.')
        else:
            job_ids = list(
                CrawlJob.objects.filter(status=CrawlJobStatus.PENDING)
                .order_by('created_at')
                .values_list('pk', flat=True)[: options['limit']]
            )
            if not job_ids:
                self.stdout.write('No pending crawl jobs.')
                return

        for job_id in job_ids:
            job = claim_job(job_id)
            if job is None:
                self.stdout.write(f'Job #{job_id} is not claimable; skipped.')
                continue
            result = execute_job(job)
            self.stdout.write(
                self.style.SUCCESS(
                    f'Job #{job_id} finished {result["status"]}: '
                    f'created={job.listings_created} updated={job.listings_updated} '
                    f'failed={job.errors}'
                )
            )
