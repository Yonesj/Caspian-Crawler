"""Resolving a source's place names onto the local hierarchy.

Two data-driven paths, in order of trust:

1. the source's own place identifier (Divar's ``city_id``, Sheypoor's slug) via
   ``SourceLocation`` — exact, and immune to spelling;
2. the free-text location the source printed, matched against
   ``LocationAlias`` and the canonical names, most specific level first.

Whichever path wins, the ancestors are read from the matched row's own chain —
a city always brings its province — and a place that is not in the reference
data leaves all three foreign keys NULL rather than a partial guess.
"""

import logging
from dataclasses import dataclass

from .text import fold_lookup, fragments

logger = logging.getLogger('north_estate.normalize')

LEVEL_PROVINCE = 'province'
LEVEL_CITY = 'city'
LEVEL_REGION = 'region'
LEVEL_RANK = {LEVEL_PROVINCE: 0, LEVEL_CITY: 1, LEVEL_REGION: 2}


@dataclass(frozen=True)
class LocationMatch:
    """Where a listing sits in the hierarchy, plus how we found out."""

    province_id: int | None = None
    city_id: int | None = None
    region_id: int | None = None
    level: str | None = None
    matched: str | None = None
    text: str | None = None

    @property
    def resolved(self) -> bool:
        return self.level is not None


class LocationIndex:
    """In-memory view of the reference data, built once per crawl.

    Rows are plain dictionaries so tests can build an index without a database;
    :meth:`load` is the thin ORM adapter over the same shape.
    """

    def __init__(self, *, provinces=(), cities=(), regions=(), aliases=(), source_locations=()):
        self._provinces = {row['id']: row for row in provinces}
        self._cities = {row['id']: row for row in cities}
        self._regions = {row['id']: row for row in regions}

        self._by_text: dict[str, tuple[str, int]] = {}
        for row in self._provinces.values():
            self._add(row['name_fa'], LEVEL_PROVINCE, row['id'])
        for row in self._cities.values():
            self._add(row['name_fa'], LEVEL_CITY, row['id'])
        for row in self._regions.values():
            self._add(row['name_fa'], LEVEL_REGION, row['id'])
        for row in aliases:
            self._add(row['alias'], row['level'], row['id'])

        self._by_source = {
            (str(row['source']), str(row['external_id'])): (row['level'], row['id'])
            for row in source_locations
            if self._known(row['level'], row['id'])
        }

    @classmethod
    def load(cls) -> 'LocationIndex':
        """Build the index from the database."""
        from core.locations.models import (
            City,
            LocationAlias,
            Province,
            Region,
            SourceLocation,
        )

        provinces = [
            {'id': row.id, 'name_fa': row.name_fa}
            for row in Province.objects.filter(is_active=True)
        ]
        cities = [
            {'id': row.id, 'name_fa': row.name_fa, 'province_id': row.province_id}
            for row in City.objects.filter(is_active=True)
        ]
        regions = [
            {'id': row.id, 'name_fa': row.name_fa, 'city_id': row.city_id}
            for row in Region.objects.filter(is_active=True)
        ]
        aliases = [
            {'alias': row.alias, 'level': level, 'id': target_id}
            for row in LocationAlias.objects.all()
            for level, target_id in [_level_and_id(row)]
            if level
        ]
        source_locations = [
            {
                'source': row.source,
                'external_id': row.external_id,
                'level': level,
                'id': target_id,
            }
            for row in SourceLocation.objects.all()
            for level, target_id in [_level_and_id(row)]
            if level
        ]
        return cls(
            provinces=provinces,
            cities=cities,
            regions=regions,
            aliases=aliases,
            source_locations=source_locations,
        )

    def resolve(
        self, *, raw_location: str | None = None, place_refs=(), source: str | None = None
    ) -> LocationMatch:
        """Best location for one listing, or an empty match."""
        target: tuple[str, int] | None = None
        matched: str | None = None

        for ref in place_refs or ():
            found = self._by_source.get((str(source), str(ref)))
            if found is not None:
                target, matched = found, 'source'
                break

        from_text = self._match_text(raw_location)
        if from_text is not None and (
            target is None or LEVEL_RANK[from_text[0]] > LEVEL_RANK[target[0]]
        ):
            target, matched = from_text, 'text'

        if target is None:
            return LocationMatch(text=raw_location or None)
        return self._build(target[0], target[1], matched, raw_location)

    # -- internals ------------------------------------------------------------
    def _add(self, text, level, target_id):
        key = fold_lookup(text or '')
        if not key or not self._known(level, target_id):
            return
        current = self._by_text.get(key)
        if current is None or LEVEL_RANK[level] > LEVEL_RANK[current[0]]:
            self._by_text[key] = (level, target_id)

    def _known(self, level, target_id) -> bool:
        if level == LEVEL_REGION:
            return target_id in self._regions
        if level == LEVEL_CITY:
            return target_id in self._cities
        if level == LEVEL_PROVINCE:
            return target_id in self._provinces
        return False

    def _match_text(self, raw_location) -> tuple[str, int] | None:
        if not raw_location:
            return None
        best: tuple[str, int] | None = None
        for candidate in [*fragments(raw_location), raw_location]:
            found = self._by_text.get(fold_lookup(candidate))
            if found is None:
                continue
            if best is None or LEVEL_RANK[found[0]] > LEVEL_RANK[best[0]]:
                best = found
        return best

    def _build(self, level, target_id, matched, text) -> LocationMatch:
        province_id = city_id = region_id = None
        if level == LEVEL_REGION:
            region = self._regions[target_id]
            region_id = region['id']
            city_id = region.get('city_id')
        elif level == LEVEL_CITY:
            city_id = target_id
        else:
            province_id = target_id

        if city_id is not None:
            city = self._cities.get(city_id)
            if city is not None:
                province_id = city.get('province_id')

        return LocationMatch(
            province_id=province_id,
            city_id=city_id,
            region_id=region_id,
            level=level,
            matched=matched,
            text=text or None,
        )


def _level_and_id(row) -> tuple[str | None, int | None]:
    if row.region_id:
        return LEVEL_REGION, row.region_id
    if row.city_id:
        return LEVEL_CITY, row.city_id
    if row.province_id:
        return LEVEL_PROVINCE, row.province_id
    return None, None
