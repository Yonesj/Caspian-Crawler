#!/bin/sh

set -eu

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.development}"

echo "Checking superuser..."
python -c "
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import IntegrityError
try:
    User = get_user_model()
    if not User.objects.filter(username='admin').exists():
        print('Creating superuser...')
        User.objects.create_superuser('admin', 'admin@gmail.com', 'admin')
    else:
        print('Superuser already exists.')
except Exception as e:
    print('Error while creating superuser:', e)
"

exec "$@"
