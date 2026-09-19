import socket

from .base import *


# GENERAL
# ------------------------------------------------------------------------------
DEBUG = True

SECRET_KEY = (
    env_str('DJANGO_SECRET_KEY')
    or env_str('SECRET_KEY')
    or 'django-insecure-dev-only-key-not-for-production'
)

ALLOWED_HOSTS = env_list(
    'DJANGO_ALLOWED_HOSTS', ['localhost', '127.0.0.1', '0.0.0.0', 'testserver']
)

# DATABASES
# ------------------------------------------------------------------------------
DATABASES = {
    'default': postgres_config(),
}

# CACHES
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "north-estate-dev",
    }
}

# STATIC
# ------------------------------------------------------------------------------
STATICFILES_DIRS = [str(BASE_DIR / 'static')]
STATIC_ROOT = str(BASE_DIR / "staticfiles")

# MEDIA
# ------------------------------------------------------------------------------
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# LOGGING
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}

# django-debug-toolbar
# ------------------------------------------------------------------------------
INSTALLED_APPS += ['debug_toolbar']

MIDDLEWARE = ['debug_toolbar.middleware.DebugToolbarMiddleware'] + MIDDLEWARE

hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
INTERNAL_IPS = [
    ip[: ip.rfind(".")] + ".1" for ip in ips
] + ["127.0.0.1"]

# drf_spectacular
# ------------------------------------------------------------------------------
if 'drf_spectacular' not in INSTALLED_APPS:
    INSTALLED_APPS += ['drf_spectacular']

REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"

SPECTACULAR_SETTINGS = {
    "TITLE": "NorthEstate API",
    "DESCRIPTION": (
        "Crawling, normalization, deduplication and search API for real-estate "
        "listings in Mazandaran, Gilan and Golestan."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SWAGGER_UI_SETTINGS": {
        "persistAuthorization": True,
    },
    "AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "ENUM_NAME_OVERRIDES": {
        "ListingStatus": "core.listings.enums.ListingStatus",
        "CrawlJobStatus": "core.crawling.enums.CrawlJobStatus",
        "CrawlJobEventLevel": "core.crawling.enums.CrawlJobEventLevel",
    },
}

# corsheaders
# ------------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = ["*"]
