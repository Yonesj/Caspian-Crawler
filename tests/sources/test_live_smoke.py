"""Opt-in checks against the real sources (``pytest -m network``).

They are deliberately excluded from the default run: the suite must never
depend on a third-party site being reachable or unchanged.  Each test makes one
list request and one detail request, paced by the configured rate limiter.
"""

import pytest

from core.sources.dto import CrawlScope
from core.sources.registry import get_adapter

pytestmark = pytest.mark.network

CASES = [('divar', '22'), ('sheypoor', 'mazandaran')]


@pytest.mark.parametrize('source,scope_id', CASES)
def test_live_first_page_and_detail_still_parse(source, scope_id):
    adapter = get_adapter(source)
    scope = CrawlScope(external_id=scope_id, page_limit=1)

    pages = list(adapter.iter_list_pages(scope))
    assert pages, f'{source}: no list page returned'
    stubs = pages[0].items
    assert stubs, f'{source}: first page had no listings'
    assert all(stub.source_id and stub.url for stub in stubs)

    detail = adapter.fetch_detail(stubs[0].source_id, url=stubs[0].url)
    assert detail.title, f'{source}: detail had no title'
    assert detail.source_id == stubs[0].source_id
