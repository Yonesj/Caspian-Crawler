"""The OpenAPI schema must stay generatable.

The schema and docs URLs are DEBUG-gated (see ``config/urls.py``), so the test
generates the schema in-process instead of requesting ``/api/schema/``; that
also keeps the check independent of URL configuration.
"""

import pytest


@pytest.mark.integration
def test_openapi_schema_is_generatable():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)

    assert schema['openapi'].startswith('3.')
    assert '/auth/token/' in schema['paths']
    assert '/api/listings/' in schema['paths']
    assert '/api/crawl-jobs/' in schema['paths']
    assert '/api/locations/provinces/' in schema['paths']

    create_job = schema['paths']['/api/crawl-jobs/']['post']
    assert create_job['requestBody']['content']['application/json']['schema'] == {
        '$ref': '#/components/schemas/CrawlJobCreate'
    }
    assert create_job['responses']['201']['content']['application/json']['schema'] == {
        '$ref': '#/components/schemas/CrawlJob'
    }
