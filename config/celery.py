"""Celery application for background crawls.

Redis is both the broker and the result backend: the same instance already backs
the shared rate-limit buckets, so running a worker needs no additional service.
Django settings are read through the ``CELERY`` namespace, which keeps every
knob in ``config/settings`` where the rest of the configuration lives.
"""

import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

app = Celery('caspian_crawler')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
