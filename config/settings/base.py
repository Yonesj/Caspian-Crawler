import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured
from rest_framework import __path__ as drf_path


BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(dotenv_path=str(BASE_DIR / ".env"))


def env_str(name, default=None):
    """Read a string, tolerating values exported with surrounding quotes.

    ``docker run -e FOO="bar"`` and some shell/CI setups keep the quotes as part
    of the value, which silently produces wrong paths and hostnames.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value


def env_bool(name, default=False):
    """Read a boolean from the environment, accepting the usual truthy spellings."""
    value = env_str(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_list(name, default=()):
    """Read a comma-separated list from the environment."""
    value = env_str(name)
    if not value:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def postgres_config(*, require_env=False, **overrides):
    """Resolve DATABASES['default'] from DATABASE_URL, else from POSTGRES_* variables.

    Connection details always come from the environment so the same settings module
    works against any PostgreSQL host (local, container, managed service).
    """
    url = env_str("DATABASE_URL")
    if url:
        parsed = urlparse(url)
        config = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": parsed.port or 5432,
        }
    else:
        raw = {
            "NAME": env_str("POSTGRES_DB"),
            "USER": env_str("POSTGRES_USER"),
            "PASSWORD": env_str("POSTGRES_PASSWORD"),
            "HOST": env_str("POSTGRES_HOST"),
            "PORT": env_str("POSTGRES_PORT"),
        }
        if require_env:
            missing = sorted(key for key, value in raw.items() if not value)
            if missing:
                raise ImproperlyConfigured(
                    "Database settings missing from the environment: "
                    f"{', '.join('POSTGRES_' + key for key in missing)}. "
                    "Set DATABASE_URL or the POSTGRES_* variables."
                )
        config = {
            "ENGINE": env_str("POSTGRES_ENGINE", "django.db.backends.postgresql"),
            "NAME": raw["NAME"] or "north_estate_db",
            "USER": raw["USER"] or "north_estate_user",
            "PASSWORD": raw["PASSWORD"] or "",
            "HOST": raw["HOST"] or "localhost",
            "PORT": int(raw["PORT"] or 5432),
        }

    config["CONN_MAX_AGE"] = int(env_str("POSTGRES_CONN_MAX_AGE", "60"))
    config.update(overrides)
    return config


def redis_url(default="redis://127.0.0.1:6379/0"):
    """Redis is used for the Celery broker/result backend and shared cache/throttles."""
    return env_str("REDIS_URL") or default

# GENERAL
# ------------------------------------------------------------------------------
LANGUAGE_CODE = 'fa'

TIME_ZONE = 'Asia/Tehran'

USE_I18N = True
USE_TZ = True

LANGUAGES = (
    ('fa', 'Persian'),
    ('en', 'English'),
)

LOCALE_PATHS = [
    os.path.join(BASE_DIR, 'locale'),
    os.path.join(drf_path[0], 'locale'),
]

# DATABASES
# ------------------------------------------------------------------------------
# Each environment builds DATABASES['default'] through postgres_config().
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# URLS
# ------------------------------------------------------------------------------
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles'
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
]
LOCAL_APPS = [
    'core.accounts',
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIDDLEWARE
# ------------------------------------------------------------------------------
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'core', 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# AUTHENTICATION
# ------------------------------------------------------------------------------
AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# STATIC
# ------------------------------------------------------------------------------
STATIC_URL = 'static/'

# MEDIA
# ------------------------------------------------------------------------------
MEDIA_URL = '/media/'

# django-rest-framework
# -------------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '1000/day',
        'user': '10000/day',
        'account_activation': '10/day',
        'password_reset': '10/hour',
    },
}

# rest_framework_simplejwt
# ------------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    'AUTH_HEADER_TYPES': ('JWT',),
}

# ADMIN
# ------------------------------------------------------------------------------
# Normalised so a quoted or slash-less value cannot silently break the route.
ADMIN_URL = (env_str("DJANGO_ADMIN_URL", "admin/") or "admin/").strip("/") + "/"

