"""Refresh the parser fixtures from the live sources.

Parser tests never touch the network, so the fixtures they read have to be
captured deliberately.  This command fetches one list page and one detail page
per source, writes *trimmed* fixtures (structure verbatim, only unrelated
entries dropped) into ``tests/sources/fixtures`` and asserts the trimming
invariant: the trimmed payload must parse to exactly the same data as the raw
capture, restricted to the retained listings.  With ``--keep-raw`` the
untrimmed pages are written to a gitignored directory for debugging.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.sources.adapters import divar as divar_adapter
from core.sources.adapters import sheypoor as sheypoor_adapter
from core.sources.adapters.divar import DETAIL_URL as DIVAR_DETAIL_URL
from core.sources.adapters.divar import LIST_URL as DIVAR_LIST_URL
from core.sources.dto import CrawlScope
from core.sources.enums import Source
from core.sources.registry import get_adapter
from core.sources.transport import FetchRequest

DEFAULT_SCOPES = {Source.DIVAR: '22', Source.SHEYPOOR: 'mazandaran'}
REF_IN_TEXT_RE = re.compile(r'\$([0-9a-f]{1,4})')


class Command(BaseCommand):
    help = 'Capture and trim source fixtures for the parser tests.'

    def add_arguments(self, parser):
        parser.add_argument('--source', required=True, choices=[str(s) for s in Source])
        parser.add_argument('--scope', default=None, help='Source place id or slug.')
        parser.add_argument(
            '--detail-index', type=int, default=0,
            help='Which listing of the captured list page to also capture in detail.',
        )
        parser.add_argument(
            '--category', default=None,
            help="Source category slug to scope the crawl (Divar: 'apartment-sell').",
        )
        parser.add_argument(
            '--detail-only', action='store_true',
            help='Capture only the detail page; leave the existing list fixture alone.',
        )
        parser.add_argument('--out', default='tests/sources/fixtures')
        parser.add_argument('--raw-dir', default='var/fixtures-raw')
        parser.add_argument('--trim', type=int, default=3, help='Listings per list fixture.')
        parser.add_argument('--keep-raw', action='store_true')

    def handle(self, *args, **options):
        source = options['source']
        scope_id = options['scope'] or DEFAULT_SCOPES[source]
        out_dir = Path(options['out'])
        out_dir.mkdir(parents=True, exist_ok=True)
        raw_dir = Path(options['raw_dir'])

        adapter = get_adapter(source)
        scope = CrawlScope(
            external_id=scope_id, label=source, category=options['category']
        )
        # Merge into the existing manifest: fixtures are refreshed one at a
        # time, so a run that replaces one detail page must not forget the rest.
        manifest_path = out_dir / f'{source}_manifest.json'
        manifest = self._load_manifest(manifest_path)
        manifest.update({
            'captured_at': datetime.now(UTC).isoformat(timespec='seconds'),
            'source': source,
            'scope': scope_id,
        })
        manifest.setdefault('files', {})

        if source == Source.DIVAR:
            self._capture_divar(adapter, scope, out_dir, raw_dir, options, manifest)
        else:
            self._capture_sheypoor(adapter, scope, out_dir, raw_dir, options, manifest)

        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
        )
        self.stdout.write(self.style.SUCCESS(f'wrote {manifest_path}'))

    def _load_manifest(self, path):
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            return {}

    # -- capture --------------------------------------------------------------
    def _fetch(self, adapter, **kwargs):
        return adapter.fetcher.fetch(FetchRequest(**kwargs))

    def _write(self, out_dir, raw_dir, name, trimmed, raw, keep_raw, manifest, meta):
        (out_dir / name).write_text(trimmed, encoding='utf-8')
        if keep_raw:
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / name).write_text(raw, encoding='utf-8')
        manifest['files'][name] = meta
        self.stdout.write(f'  {name}: {meta}')

    def _capture_divar(self, adapter, scope, out_dir, raw_dir, options, manifest):
        list_response = self._fetch(
            adapter, method='POST', url=DIVAR_LIST_URL, source=Source.DIVAR,
            json_body=divar_adapter.list_body(scope),
        )
        raw_payload = json.loads(list_response.text)
        raw_page = divar_adapter.parse_list_page(raw_payload, scope, 1)
        if options['detail_only']:
            self._capture_divar_detail(
                adapter, scope, raw_page, out_dir, raw_dir, options, manifest
            )
            return
        keep = options['trim']
        trimmed = {
            'list_widgets': [
                widget
                for widget in raw_payload.get('list_widgets', [])
                if widget.get('widget_type') == divar_adapter.ROW_WIDGET
            ][:keep],
            'pagination': raw_payload.get('pagination') or {},
        }
        trimmed_page = divar_adapter.parse_list_page(trimmed, scope, 1)
        self._assert_same(trimmed_page.items, raw_page.items[:keep], 'divar list')
        self._write(
            out_dir, raw_dir, 'divar_list_page1.json',
            json.dumps(trimmed, ensure_ascii=False, indent=2) + '\n',
            list_response.text,
            options['keep_raw'], manifest,
            {'url': DIVAR_LIST_URL, 'listings': len(trimmed_page.items),
             'category': scope.category},
        )

        self._capture_divar_detail(
            adapter, scope, raw_page, out_dir, raw_dir, options, manifest
        )

    def _capture_divar_detail(self, adapter, scope, raw_page, out_dir, raw_dir, options, manifest):
        if not raw_page.items:
            raise CommandError('divar: capture returned no listings')
        stub = raw_page.items[min(options['detail_index'], len(raw_page.items) - 1)]
        detail_response = self._fetch(
            adapter,
            method='GET',
            url=DIVAR_DETAIL_URL.format(token=stub.source_id),
            source=Source.DIVAR,
        )
        detail_payload = json.loads(detail_response.text)
        detail_trimmed = {
            key: value
            for key, value in detail_payload.items()
            if key in {'sections', 'seo', 'city', 'contact', 'share'}
        }
        raw_detail = divar_adapter.parse_detail(detail_payload, stub.source_id)
        trimmed_detail = divar_adapter.parse_detail(detail_trimmed, stub.source_id)
        self._assert_same([trimmed_detail], [raw_detail], 'divar detail')
        self._write(
            out_dir, raw_dir, f'divar_detail_{stub.source_id}.json',
            json.dumps(detail_trimmed, ensure_ascii=False, indent=2) + '\n',
            detail_response.text,
            options['keep_raw'], manifest,
            {'url': DIVAR_DETAIL_URL.format(token=stub.source_id), 'listing': stub.source_id,
             'category': scope.category},
        )

    def _capture_sheypoor(self, adapter, scope, out_dir, raw_dir, options, manifest):
        list_response = self._fetch(
            adapter,
            method='GET',
            url=sheypoor_adapter.LIST_URL.format(slug=scope.external_id),
            source=Source.SHEYPOOR,
        )
        raw_page = sheypoor_adapter.parse_list_page(list_response.text, scope, 1)
        if options['detail_only']:
            self._capture_sheypoor_detail(
                adapter, scope, raw_page, out_dir, raw_dir, options, manifest
            )
            return
        keep = options['trim']
        trimmed_html = trim_sheypoor_page(
            list_response.text, [item.source_id for item in raw_page.items[:keep]],
            detail=False,
        )
        trimmed_page = sheypoor_adapter.parse_list_page(trimmed_html, scope, 1)
        self._assert_same(trimmed_page.items, raw_page.items[:keep], 'sheypoor list')
        self._write(
            out_dir, raw_dir, 'sheypoor_list_page1.html', trimmed_html,
            list_response.text, options['keep_raw'], manifest,
            {'url': list_response.url, 'listings': len(trimmed_page.items),
             'category': scope.category},
        )

        self._capture_sheypoor_detail(
            adapter, scope, raw_page, out_dir, raw_dir, options, manifest
        )

    def _capture_sheypoor_detail(self, adapter, scope, raw_page, out_dir, raw_dir, options, manifest):
        stub = raw_page.items[min(options['detail_index'], len(raw_page.items) - 1)]
        detail_response = self._fetch(
            adapter, method='GET', url=stub.url, source=Source.SHEYPOOR
        )
        trimmed_detail_html = trim_sheypoor_page(
            detail_response.text, [stub.source_id], detail=True
        )
        raw_detail = sheypoor_adapter.parse_detail(
            detail_response.text, stub.source_id, stub.url
        )
        trimmed_detail = sheypoor_adapter.parse_detail(
            trimmed_detail_html, stub.source_id, stub.url
        )
        self._assert_detail_same(trimmed_detail, raw_detail, 'sheypoor detail')
        self._write(
            out_dir, raw_dir, f'sheypoor_detail_{stub.source_id}.html',
            trimmed_detail_html, detail_response.text, options['keep_raw'], manifest,
            {'url': stub.url, 'listing': stub.source_id, 'category': scope.category},
        )

    # -- assertions -----------------------------------------------------------
    def _assert_same(self, trimmed, raw, label):
        trimmed_data = [item.__dict__ for item in trimmed]
        raw_data = [item.__dict__ for item in raw]
        if trimmed_data != raw_data:
            raise CommandError(f'{label}: trimmed fixture does not parse identically')

    def _assert_detail_same(self, trimmed, raw, label):
        for field in ('source_id', 'url', 'title', 'description', 'raw_location',
                      'raw_price', 'attributes', 'image_urls', 'published_at_text',
                      'category_path', 'place_refs'):
            if getattr(trimmed, field) != getattr(raw, field):
                raise CommandError(f'{label}: field {field} changed while trimming')


# -- Sheypoor flight trimming -------------------------------------------------
def referenced_ids(raw_text: str) -> set[str]:
    return set(REF_IN_TEXT_RE.findall(raw_text))


def trim_sheypoor_page(html: str, keep_ids: list[str], *, detail: bool) -> str:
    """Rebuild the flight stream with only the rows the retained listings need."""
    payload = sheypoor_adapter.decode_flight_payload(html)
    rows = sheypoor_adapter.flight_rows_ordered(payload)
    by_id = dict(rows)

    if detail:
        seeds = [row_id for row_id, text in rows if '"publicListingDetails"' in text]
    else:
        seeds = []
        for row_id, text in rows:
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not sheypoor_adapter.is_listing(value):
                continue
            source_id = str(
                value.get('id') or sheypoor_adapter.source_id_from_url(value.get('url', ''))
            )
            if source_id in keep_ids:
                seeds.append(row_id)
        seeds = seeds[: len(keep_ids)]

    if not seeds:
        raise CommandError('sheypoor: nothing to keep when trimming this page')

    keep = _reference_closure(seeds, by_id)
    stream = '\n'.join(
        f'{row_id}:{by_id[row_id]}' for row_id, _ in rows if row_id in keep
    ) + '\n'
    return sheypoor_document(stream)


def _reference_closure(seeds, by_id):
    keep: set[str] = set()
    pending = list(seeds)
    while pending:
        row_id = pending.pop()
        if row_id in keep or row_id not in by_id:
            continue
        keep.add(row_id)
        pending.extend(referenced_ids(by_id[row_id]) - keep)
    return keep


def sheypoor_document(stream: str) -> str:
    chunk = json.dumps(stream, ensure_ascii=False).replace('</', '<\\/')
    return (
        '<!doctype html>\n<html lang="fa">\n<head><meta charset="utf-8">'
        '<title>CaspianCrawler fixture</title></head>\n<body>\n'
        f'<script>self.__next_f.push([1,{chunk}])</script>\n'
        '</body>\n</html>\n'
    )
