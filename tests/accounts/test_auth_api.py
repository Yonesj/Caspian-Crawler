import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.integration


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username='operator', password='s3cret-pass'
    )


def test_project_owns_the_user_model():
    assert get_user_model()._meta.label == 'accounts.User'


def test_token_obtain_returns_access_and_refresh(client, user):
    response = client.post(
        reverse('accounts:token-obtain'),
        data=json.dumps({'username': 'operator', 'password': 's3cret-pass'}),
        content_type='application/json',
    )

    assert response.status_code == 200
    assert {'access', 'refresh'} <= set(response.json())
