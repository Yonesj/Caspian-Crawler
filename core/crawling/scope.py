"""Turn a saved :class:`CrawlJob` scope into a source :class:`CrawlScope`.

The lookup is data-driven in both directions:

* the place comes from ``SourceLocation`` rows (never a city list in code),
  most specific level first, falling back province-ward;
* the category comes from an explicit job override, else ``SourceCategory``,
  else nothing -- and "nothing" is a valid outcome that the job records.
"""

from core.locations.models import SourceLocation
from core.sources.categories import resolve_category
from core.sources.config import policy_for
from core.sources.dto import CrawlScope
from core.sources.errors import SourceDisabled

from .errors import ScopeResolutionError


def resolve_source_place(job) -> str:
    """The source's own identifier for the job's place, or raise.

    Walks the hierarchy from the most specific level the job was scoped to and
    keeps going up: a region-only mapping falls back to its city and then its
    province, so a source that only publishes city-level places still works.
    """
    for level, target_id in _place_chain(job):
        mapping = SourceLocation.objects.filter(
            source=job.source, **{level: target_id}
        ).first()
        if mapping is not None:
            return mapping.external_id

    raise ScopeResolutionError(
        f'No {job.source} location mapping for crawl scope '
        f'(province={job.province_id}, city={job.city_id}, region={job.region_id}). '
        f'Add a SourceLocation row for this place before crawling it.'
    )


def _place_chain(job):
    """(level, id) pairs to try, most specific first."""
    if job.region_id:
        region = job.region
        yield ('region', region.pk)
        yield ('city', region.city_id)
        yield ('province', region.city.province_id)
    elif job.city_id:
        city = job.city
        yield ('city', city.pk)
        yield ('province', city.province_id)
    elif job.province_id:
        yield ('province', job.province_id)


def build_scope(job) -> CrawlScope:
    """Resolve ``job`` into a :class:`CrawlScope` or raise a typed error."""
    policy = policy_for(job.source)
    if not policy.enabled:
        raise SourceDisabled(f'Crawling is disabled for source {job.source!r}.')

    external_id = resolve_source_place(job)
    category = job.source_category or resolve_category(
        job.source, job.transaction_type, job.property_type
    )
    return CrawlScope(
        external_id=external_id,
        label=_label(job),
        page_limit=job.page_limit,
        category=category or None,
    )


def _label(job) -> str:
    target = job.region or job.city or job.province
    return str(target) if target is not None else ''
