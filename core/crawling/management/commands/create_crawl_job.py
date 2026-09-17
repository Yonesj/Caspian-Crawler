"""Register a crawl job from the command line.

Resolving the scope here (not in the worker) means an unmapped place, an
ambiguous city code or a disabled source fails immediately with a clear error
instead of producing a queued job that can never run.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.crawling.models import create_job, queue_job
from core.listings.enums import PropertyType, TransactionType
from core.locations.models import City, Province, Region
from core.sources.enums import Source
from core.sources.errors import SourceError


class Command(BaseCommand):
    help = 'Create a crawl job (and enqueue it unless --no-enqueue is given).'

    def add_arguments(self, parser):
        parser.add_argument('--source', required=True, choices=Source.values)
        parser.add_argument('--province', help='Province code, e.g. mazandaran.')
        parser.add_argument('--city', help='City code, e.g. sari.')
        parser.add_argument('--region', help='Region code, e.g. farhang-shahr.')
        parser.add_argument(
            '--transaction', default=TransactionType.UNSPECIFIED,
            choices=TransactionType.values,
        )
        parser.add_argument(
            '--property', dest='property_type', default=PropertyType.OTHER,
            choices=PropertyType.values,
        )
        parser.add_argument('--pages', type=int, help='Maximum list pages to crawl.')
        parser.add_argument(
            '--category', default='',
            help='Override the resolved source category slug.',
        )
        parser.add_argument('--user', help='Username to attribute the job to.')
        parser.add_argument(
            '--enqueue', dest='enqueue', action='store_true', default=True,
            help='Publish the job to Celery (default).',
        )
        parser.add_argument(
            '--no-enqueue', dest='enqueue', action='store_false',
            help='Create the job without publishing it.',
        )

    def handle(self, *args, **options):
        target = _resolve_location(options)
        if options['pages'] is not None and options['pages'] < 1:
            raise CommandError('--pages must be at least 1.')

        try:
            job = create_job(
                source=options['source'],
                province=target.get('province'),
                city=target.get('city'),
                region=target.get('region'),
                transaction_type=options['transaction'],
                property_type=options['property_type'],
                page_limit=options['pages'],
                source_category=options['category'],
                requested_by=_user(options.get('user')),
            )
        except SourceError as exc:
            raise CommandError(f'Cannot create the job: {exc}')

        if options['enqueue']:
            queue_job(job)

        self.stdout.write(
            self.style.SUCCESS(
                f'Crawl job #{job.pk} created: source={job.source} '
                f'place={job.source_external_id!r} category={job.source_category or "-"} '
                f'status={job.status}'
            )
        )


def _resolve_location(options):
    """Turn the CLI flags into exactly one scope target.

    Parent flags may be used to disambiguate a code that exists in more than one
    province; the most specific flag is what the job is scoped to.
    """
    province_code = options.get('province')
    city_code = options.get('city')
    region_code = options.get('region')

    if region_code:
        queryset = Region.objects.filter(code=region_code).select_related('city__province')
        if city_code:
            queryset = queryset.filter(city__code=city_code)
        if province_code:
            queryset = queryset.filter(city__province__code=province_code)
        return {'region': _one(queryset, 'region', region_code)}

    if city_code:
        queryset = City.objects.filter(code=city_code).select_related('province')
        if province_code:
            queryset = queryset.filter(province__code=province_code)
        return {'city': _one(queryset, 'city', city_code)}

    if province_code:
        return {'province': _one(Province.objects.filter(code=province_code), 'province', province_code)}

    raise CommandError(
        'Specify a scope: --province, --city or --region '
        '(parent flags may be added to disambiguate a code).'
    )


def _one(queryset, label, code):
    matches = list(queryset)
    if not matches:
        raise CommandError(f'No {label} with code {code!r}.')
    if len(matches) > 1:
        options = ', '.join(str(row) for row in matches)
        raise CommandError(
            f'{label} code {code!r} matches more than one place ({options}); '
            f'add the parent flag to disambiguate.'
        )
    return matches[0]


def _user(username):
    if not username:
        return None
    model = get_user_model()
    try:
        return model.objects.get(**{model.USERNAME_FIELD: username})
    except model.DoesNotExist:
        raise CommandError(f'No user named {username!r}.')
