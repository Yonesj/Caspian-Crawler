import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.crawling import tasks
from core.crawling.enums import CrawlJobStatus
from core.listings.models import Listing
from core.sources.enums import Source
from tests.crawling.conftest import FakeAdapter, make_detail, make_stub, page

pytestmark = pytest.mark.integration


def _client(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def test_crawl_options_are_public_and_use_normalized_vocabulary():
    response = _client().get('/api/crawl-options/')

    assert response.status_code == 200
    payload = response.json()
    assert {'value': 'divar', 'label': 'Divar'} in payload['sources']
    assert {'value': 'sale', 'label': 'Sale / purchase'} in payload['transaction_types']
    assert {'value': 'apartment', 'label': 'Apartment'} in payload['property_types']
    assert 'source_categories' not in payload


def test_creating_a_job_requires_authentication(places):
    response = _client().post(
        '/api/crawl-jobs/',
        {
            'source': 'divar',
            'transaction_type': 'sale',
            'property_type': 'apartment',
            'scope': {'city_id': places.city.pk},
        },
        format='json',
    )

    assert response.status_code == 401


def test_create_job_uses_domain_service_and_queues_it(
    places, source_categories, mocker
):
    user = get_user_model().objects.create_user(username='operator')
    publish = mocker.patch('core.crawling.tasks.run_crawl_job.delay')

    response = _client(user).post(
        '/api/crawl-jobs/',
        {
            'source': 'divar',
            'transaction_type': 'sale',
            'property_type': 'apartment',
            'page_limit': 2,
            'scope': {'city_id': places.city.pk},
        },
        format='json',
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload['status'] == CrawlJobStatus.QUEUED
    assert payload['requested_by'] == 'operator'
    assert payload['scope']['level'] == 'city'
    assert payload['scope']['code'] == 'sari'
    assert 'source_external_id' not in payload
    assert 'source_category' not in payload
    job = user.crawl_jobs.get()
    assert job.page_limit == 2
    assert job.source_external_id == '22'
    assert publish.call_args.args == (job.pk,)


@pytest.mark.parametrize(
    'scope',
    [
        {},
        {'province_id': 1, 'city_id': 1},
        {'region_id': 999999},
    ],
)
def test_create_job_rejects_invalid_scope(places, source_categories, scope):
    user = get_user_model().objects.create_user(username=f'user-{len(scope)}')

    response = _client(user).post(
        '/api/crawl-jobs/',
        {'source': 'divar', 'scope': scope},
        format='json',
    )

    assert response.status_code == 400
    assert 'scope' in response.json()


def test_create_job_rejects_page_limit_outside_model_range(
    places, source_categories
):
    user = get_user_model().objects.create_user(username='invalid-page-limit')

    response = _client(user).post(
        '/api/crawl-jobs/',
        {
            'source': 'divar',
            'page_limit': 32768,
            'scope': {'city_id': places.city.pk},
        },
        format='json',
    )

    assert response.status_code == 400
    assert 'page_limit' in response.json()


def test_users_see_only_their_jobs_while_staff_see_all(job_factory):
    alice = get_user_model().objects.create_user(username='alice')
    bob = get_user_model().objects.create_user(username='bob')
    staff = get_user_model().objects.create_user(username='staff', is_staff=True)
    alice_job = job_factory(requested_by=alice)
    bob_job = job_factory(source=Source.SHEYPOOR, requested_by=bob)

    alice_response = _client(alice).get('/api/crawl-jobs/')
    staff_response = _client(staff).get('/api/crawl-jobs/')

    assert [row['id'] for row in alice_response.json()['results']] == [alice_job.pk]
    assert 'events' not in alice_response.json()['results'][0]
    assert {row['id'] for row in staff_response.json()['results']} == {
        alice_job.pk,
        bob_job.pk,
    }
    assert _client(alice).get(f'/api/crawl-jobs/{bob_job.pk}/').status_code == 404


def test_job_detail_includes_counters_report_and_event_history(job_factory):
    user = get_user_model().objects.create_user(username='owner')
    job = job_factory(requested_by=user)
    job.transition_to(
        CrawlJobStatus.RUNNING,
        reason='claimed',
        pages_fetched=2,
        report={
            'phase': 'running',
            'source_external_id': '22',
            'source_category': 'apartment-sell',
        },
    )

    response = _client(user).get(f'/api/crawl-jobs/{job.pk}/')

    assert response.status_code == 200
    payload = response.json()
    assert payload['pages_fetched'] == 2
    assert payload['report'] == {'phase': 'running'}
    assert payload['events'][0]['reason'] == 'claimed'


def test_api_workflow_reruns_without_duplicate_listings(
    places, source_categories, monkeypatch
):
    user = get_user_model().objects.create_user(username='workflow-operator')
    client = _client(user)
    published = []
    adapter = FakeAdapter(
        {'same-listing': make_detail('same-listing')},
        pages=[page(make_stub('same-listing'))],
    )
    monkeypatch.setattr(tasks.run_crawl_job, 'delay', published.append)
    monkeypatch.setattr(
        'core.crawling.runner.get_adapter', lambda source, **kwargs: adapter
    )
    request = {
        'source': 'divar',
        'transaction_type': 'sale',
        'property_type': 'apartment',
        'scope': {'city_id': places.city.pk},
    }

    first_response = client.post('/api/crawl-jobs/', request, format='json')
    tasks.run_crawl_job(published.pop(0))
    second_response = client.post('/api/crawl-jobs/', request, format='json')
    tasks.run_crawl_job(published.pop(0))

    first_status = client.get(
        f"/api/crawl-jobs/{first_response.json()['id']}/"
    ).json()
    second_status = client.get(
        f"/api/crawl-jobs/{second_response.json()['id']}/"
    ).json()
    listing_search = APIClient().get('/api/listings/', {'search': 'آپارتمان'})

    assert first_status['status'] == CrawlJobStatus.SUCCEEDED
    assert first_status['listings_created'] == 1
    assert second_status['status'] == CrawlJobStatus.SUCCEEDED
    assert second_status['listings_updated'] == 1
    assert Listing.objects.count() == 1
    assert listing_search.json()['count'] == 1
