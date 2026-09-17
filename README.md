# NorthEstate

A Django/PostgreSQL backend that crawls, normalizes, deduplicates and exposes
real-estate listings from public Iranian sources in the northern provinces
**Mazandaran**, **Gilan** and **Golestan**.

The goal is a backend that is runnable, extensible, fault-tolerant and
deployable — not a complete commercial platform. Extraction breadth is
deliberately traded for a sound, well-tested architecture.

## Status

| Milestone | Scope | State |
| --- | --- | --- |
| 0 | Foundation: settings, env-driven DB, `accounts`, schema docs, test harness | done |
| 1 | Domain data: provinces/cities, listings, status history | planned |
| 2 | Source integrations: Divar + Sheypoor adapters, retry/backoff, rate limits | planned |
| 3 | Normalization: Persian digits, Toman/Rial, Jalali dates, locations | planned |
| 4 | Crawl pipeline: jobs, Celery worker + beat, observability | planned |
| 5 | Deduplication and listing lifecycle | planned |
| 6 | API endpoints, Dockerfile, docker-compose, full README | planned |

## Requirements

- Python 3.14 (see `.python-version`) and [uv](https://docs.astral.sh/uv/)
- PostgreSQL (development and production)
- Redis (required from milestone 4 onwards, for Celery and shared throttles)
- Playwright browsers — only needed for the optional browser fallback fetcher

## Local setup

```bash
# 1. Dependencies
uv sync

# 2. Configuration
cp .env.example .env      # then edit the values

# 3. Database (run once as a PostgreSQL superuser)
#    CREATE USER north_estate_user WITH PASSWORD '...';
#    CREATE DATABASE north_estate_db OWNER north_estate_user;
#    ALTER ROLE north_estate_user CREATEDB;   -- lets pytest-django build its test DB

# 4. Schema and an admin account
uv run python manage.py migrate
uv run python manage.py createsuperuser

# 5. Run
uv run python manage.py runserver
```

Then:

- Swagger UI — `/api/docs/`
- ReDoc — `/api/redoc/`
- OpenAPI schema — `/api/schema/`
- JWT token — `POST /auth/token/` (`{"username": ..., "password": ...}`)
- Django admin — `/admin/`

The schema and docs URLs are registered only when `DEBUG` is true, so they are
available in development and absent in production by design. The test suite
generates the schema in-process instead of requesting those URLs.

### Settings modules

`config/settings/development.py` is used by `manage.py`, `test.py` by pytest and
`production.py` by `wsgi.py`/`asgi.py`. Database connection details always come
from the environment (`DATABASE_URL` or the `POSTGRES_*` variables) so the same
code runs against any PostgreSQL host.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Required in production; must be a long random string |
| `DJANGO_SETTINGS_MODULE` | Settings module to load |
| `DJANGO_ADMIN_URL` | Admin path, default `admin/` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames (required in production) |
| `DATABASE_URL` | Full connection URL; alternative to the `POSTGRES_*` set |
| `POSTGRES_DB` / `_USER` / `_PASSWORD` / `_HOST` / `_PORT` | Individual connection settings |
| `POSTGRES_CONN_MAX_AGE` | Persistent connection lifetime in seconds |
| `REDIS_URL` | Celery broker/result backend and shared cache |
| `CORS_ALLOWED_ORIGINS` | Comma-separated origins (production) |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | Opt-in TLS hardening (production) |

Values may be quoted or unquoted; surrounding quotes are stripped. Never commit
a populated `.env`.

## Running tests

```bash
uv run pytest              # default: fast, no network, no browser
uv run pytest -m network   # refreshes parsers against live sources (opt-in)
uv run pytest -m playwright
```

Test markers: `integration` (database/API), `network` (real sources) and
`playwright` (browser binaries). The default run deselects the last two so CI
never depends on remote sites being reachable or unchanged.

Tests run against PostgreSQL, so the configured role needs `CREATEDB` to let
pytest-django create `test_<database>`. Without it, only non-database tests run.

Parsers are tested against committed fixtures captured from each source; no
default test performs live requests.

## Project layout

```text
config/settings/     # split settings: base / development / test / production
core/accounts/       # project user model and JWT endpoints
core/                # domain apps: locations, listings, crawling, sources, api
tests/               # unit, integration and fixture-based parser tests
```

Responsibilities stay separated: crawler/source integration, normalization,
deduplication, job orchestration and API code each live in their own module, and
neither models nor views contain source-specific parsing logic.

## Sources

Only publicly accessible data is targeted. No authentication bypass, CAPTCHA
bypass, anti-bot evasion or private-data scraping is implemented, and each
source is handled according to its published restrictions.

| Source | Access notes (verified during reconnaissance) | Approach |
| --- | --- | --- |
| Divar | `divar.ir/robots.txt` and `api.divar.ir/robots.txt` allow all paths. The public web API used by divar.ir itself returns JSON: `POST /v8/postlist/w/search` (25 listings per page, cursor pagination) and `GET /v8/posts-v2/web/<token>` (detail). City ids are resolved from the server-rendered listing page. | HTTP/JSON adapter, no browser |
| Sheypoor | `robots.txt` allows listing paths and `page_num` pagination; it disallows `/search`, `/session`, `/pro` and bare query strings, which the adapter avoids. Listings are embedded in the server-rendered HTML; a public `/api/v10.0.0/...` JSON API also exists. | HTTP adapter + HTML parsing, no browser |

## Key architectural decisions

- **HTTP-first crawling, Playwright as an optional fallback.** Both current
  sources expose machine-readable data, so the default path is fast and
  deterministic. A browser fetcher is available for sources that only render
  client-side and is never loaded unless used.
- **Celery + Redis for background work.** Crawling never happens inside a
  request; jobs have an observable lifecycle and a retry policy, and Redis also
  backs shared rate-limiting and throttle state across workers.
- **Celery beat for optional periodic crawls**, driven by database-backed
  schedules (disabled by default).
- **Deduplication is conservative.** Same-source repeats and updates are
  resolved deterministically from the source's own identifier, never from the
  URL. Cross-source matches are only ever recorded as candidates for review —
  listings are never merged automatically, because a false-positive merge is
  worse than a missed duplicate.
- **Money is stored in a single canonical unit (Toman)** with an explicit
  currency and flags for negotiable/unspecified prices; "not specified" is never
  stored as `0`.
- **Locations are data, not code.** Provinces, cities and each source's external
  location identifiers live in the database, so adding a city requires no code
  change.
