from .base import *


# GENERAL
# ------------------------------------------------------------------------------
DEBUG = False

# Long enough that PyJWT does not warn about HMAC key size while signing.
SECRET_KEY = 'django-insecure-test-only-key-at-least-32-bytes'

ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']

# DATABASES
# ------------------------------------------------------------------------------
# Tests always run against PostgreSQL: the crawler relies on SELECT ... FOR UPDATE
# SKIP LOCKED and JSONField behaviour that SQLite does not reproduce faithfully.
# CONN_MAX_AGE is disabled so the test database can always be dropped cleanly.
DATABASES = {
    'default': postgres_config(CONN_MAX_AGE=0),
}

# CACHES
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "north-estate-test",
    }
}

# AUTHENTICATION
# ------------------------------------------------------------------------------
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# drf_spectacular
# ------------------------------------------------------------------------------
# The schema/docs URLs are DEBUG-gated, so tests generate the schema in-process
# instead of fetching it.  The app is registered here explicitly because
# drf-spectacular is a development-only dependency.
if 'drf_spectacular' not in INSTALLED_APPS:
    INSTALLED_APPS += ['drf_spectacular']

REST_FRAMEWORK['DEFAULT_SCHEMA_CLASS'] = 'drf_spectacular.openapi.AutoSchema'

# LOGGING
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "null": {"class": "logging.NullHandler"},
    },
    "root": {"level": "ERROR", "handlers": ["null"]},
}
