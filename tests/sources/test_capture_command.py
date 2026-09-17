import json
from io import StringIO

import httpx
import pytest
import respx
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from core.sources.adapters import divar, sheypoor
from core.sources.dto import CrawlScope
from core.sources.enums import Source
from tests.sources.conftest import (
    DIVAR_COMMERCIAL_RENT,
    SHEYPOOR_LAND_SALE,
    fixture_text,
    make_policy,
)

# Pacing is asserted in the rate-limit tests; here it would only slow the suite.
NO_PACING = override_settings(
    CRAWL_POLICIES={str(source): make_policy() for source in Source}
)


def run_capture(**options):
    out = StringIO()
    args = ['capture_source_fixtures']
    for key, value in options.items():
        flag = '--' + key.replace('_', '-')
        if value is True:
            args.append(flag)
        else:
            args.extend([flag, str(value)])
    call_command(*args, stdout=out)
    return out.getvalue()


@respx.mock
@NO_PACING
def test_divar_capture_trims_and_verifies(tmp_path):
    raw_fixture = fixture_text('divar_list_page1.json')
    detail_fixture = fixture_text(DIVAR_COMMERCIAL_RENT)
    respx.post(divar.LIST_URL).mock(return_value=httpx.Response(200, text=raw_fixture))
    respx.get(url__startswith='https://api.divar.ir/v8/posts-v2/web/').mock(
        return_value=httpx.Response(200, text=detail_fixture)
    )
    out_dir = tmp_path / 'fixtures'
    raw_dir = tmp_path / 'raw'

    run_capture(
        source='divar', out=out_dir, raw_dir=raw_dir, trim=2, detail_index=0, keep_raw=True
    )

    trimmed = json.loads((out_dir / 'divar_list_page1.json').read_text(encoding='utf-8'))
    assert len(trimmed['list_widgets']) == 2
    assert trimmed['pagination']

    source_payload = json.loads(raw_fixture)
    expected = divar.parse_list_page(source_payload, CrawlScope('22'), 1).items[:2]
    assert divar.parse_list_page(trimmed, CrawlScope('22'), 1).items == expected

    # The raw copy is the untrimmed capture, kept for debugging.
    raw_copy = json.loads((raw_dir / 'divar_list_page1.json').read_text(encoding='utf-8'))
    assert len(raw_copy['list_widgets']) == len(source_payload['list_widgets'])

    manifest = json.loads((out_dir / 'divar_manifest.json').read_text(encoding='utf-8'))
    assert manifest['source'] == 'divar'
    assert set(manifest['files']) == {
        'divar_list_page1.json',
        f'divar_detail_{expected[0].source_id}.json',
    }
    assert 'captured_at' in manifest


@respx.mock
@NO_PACING
def test_sheypoor_capture_trims_and_verifies(tmp_path):
    list_html = fixture_text('sheypoor_list_page1.html')
    detail_html = fixture_text(SHEYPOOR_LAND_SALE)
    respx.get(url__startswith='https://www.sheypoor.com/s/').mock(
        return_value=httpx.Response(200, text=list_html)
    )
    respx.get(url__startswith='https://www.sheypoor.com/v/').mock(
        return_value=httpx.Response(200, text=detail_html)
    )
    out_dir = tmp_path / 'fixtures'
    raw_dir = tmp_path / 'raw'

    run_capture(source='sheypoor', out=out_dir, raw_dir=raw_dir, trim=2, keep_raw=True)

    trimmed_html = (out_dir / 'sheypoor_list_page1.html').read_text(encoding='utf-8')
    full_page = sheypoor.parse_list_page(list_html, CrawlScope('mazandaran'), 1)
    trimmed_page = sheypoor.parse_list_page(trimmed_html, CrawlScope('mazandaran'), 1)
    assert trimmed_page.items == full_page.items[:2]

    raw_copy = (raw_dir / 'sheypoor_list_page1.html').read_text(encoding='utf-8')
    assert raw_copy == list_html

    detail_files = [p for p in out_dir.glob('sheypoor_detail_*.html')]
    assert len(detail_files) == 1
    detail = sheypoor.parse_detail(
        detail_files[0].read_text(encoding='utf-8'), '464398666', 'https://example.test'
    )
    assert detail.attributes['متراژ'] == '۹۵۰'


@respx.mock
@NO_PACING
def test_capture_is_repeatable(tmp_path):
    respx.post(divar.LIST_URL).mock(
        return_value=httpx.Response(200, text=fixture_text('divar_list_page1.json'))
    )
    respx.get(url__startswith='https://api.divar.ir/v8/posts-v2/web/').mock(
        return_value=httpx.Response(
            200, text=fixture_text(DIVAR_COMMERCIAL_RENT)
        )
    )
    out_dir = tmp_path / 'fixtures'

    run_capture(source='divar', out=out_dir, raw_dir=tmp_path / 'raw', trim=2)
    first = (out_dir / 'divar_list_page1.json').read_text(encoding='utf-8')
    run_capture(source='divar', out=out_dir, raw_dir=tmp_path / 'raw', trim=2)

    assert (out_dir / 'divar_list_page1.json').read_text(encoding='utf-8') == first
    assert len(list(out_dir.glob('divar_detail_*.json'))) == 1


@respx.mock
@NO_PACING
def test_capture_refuses_a_page_without_listings(tmp_path):
    respx.post(divar.LIST_URL).mock(
        return_value=httpx.Response(200, json={'list_widgets': [], 'pagination': {}})
    )

    with pytest.raises(CommandError):
        run_capture(source='divar', out=tmp_path, raw_dir=tmp_path / 'raw', trim=2)
