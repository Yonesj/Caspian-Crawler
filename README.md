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
| 1 | Domain data: provinces/cities/regions, listings, status history | done |
| 2 | Source integrations: Divar + Sheypoor adapters, retry/backoff, rate limits | done |
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

# 4. Schema, reference locations and an admin account
uv run python manage.py migrate
uv run python manage.py seed_locations     # idempotent; safe to re-run
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
| `REDIS_URL` | Shared Redis: rate-limit buckets now, Celery broker/result backend later |
| `CRAWL_USER_AGENT` | User agent sent to crawl sources; production should carry a contact |
| `CRAWL_RATE_LIMIT_BACKEND` | `memory` (default) or `redis` (default in production) |
| `CORS_ALLOWED_ORIGINS` | Comma-separated origins (production) |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | Opt-in TLS hardening (production) |

Per-source crawling policy is overridable without a deploy, with
`CRAWL_<SOURCE>_<FIELD>` where source is `DIVAR` or `SHEYPOOR` and field is one
of `REQUESTS_PER_SECOND`, `BURST`, `TIMEOUT_SECONDS`, `CONNECT_TIMEOUT_SECONDS`,
`MAX_ATTEMPTS`, `BACKOFF_BASE_SECONDS`, `BACKOFF_FACTOR`, `BACKOFF_MAX_SECONDS`,
`MAX_RETRY_AFTER_SECONDS`, `MAX_RESPONSE_BYTES`, `ENABLED` — for example
`CRAWL_DIVAR_REQUESTS_PER_SECOND=0.25`.

Values may be quoted or unquoted; surrounding quotes are stripped. Never commit
a populated `.env`.

## Running tests

```bash
uv run pytest               # default: fast, offline, no browser
uv run pytest tests/sources # crawler layer only (no database needed)
uv run pytest -m network    # opt-in checks against the live sources
uv run pytest -m playwright
```

Test markers: `integration` (database/API), `network` (real sources) and
`playwright` (browser binaries). The default run deselects the last two so CI
never depends on remote sites being reachable or unchanged.

Tests run against PostgreSQL, so the configured role needs `CREATEDB` to let
pytest-django create `test_<database>`. Without it, only non-database tests run.

Covered so far: authentication endpoints, schema generation, the location
hierarchy and its integrity constraints, the `seed_locations` command
(idempotency, dry-run, malformed input), the listing model's identity, price,
ordering and status-history rules, and the whole crawler layer — retry/backoff
and `Retry-After` behaviour, both rate limiters, and both source parsers.

Parsers and the transport are tested against committed fixtures and a mocked
HTTP transport, so no default test performs a live request; `-m network` runs
the opt-in smoke test that re-checks both sources end to end.

### Refreshing source fixtures

Parser fixtures under `tests/sources/fixtures/` are captured from the live
sources and trimmed to a few listings each, keeping the source's exact structure
(keys, nesting and escaping). The capture command re-fetches, trims and — before
writing anything — asserts that the trimmed payload parses to exactly the same
data as the untrimmed capture:

```bash
uv run python manage.py capture_source_fixtures --source divar --keep-raw
uv run python manage.py capture_source_fixtures --source sheypoor --keep-raw
```

`--trim N` controls how many listings are kept, `--scope` overrides the place
id/slug, `--detail-index` picks which listing is also captured in detail, and
untrimmed copies go to the gitignored `var/fixtures-raw/`.

## Project layout

```text
config/settings/     # split settings: base / development / test / production
core/accounts/       # project user model and JWT endpoints
core/locations/      # province/city/region reference data + seed command
core/listings/       # normalized listing, images, status history
core/sources/        # source vocabulary, adapters, HTTP transport, rate limiting
tests/               # unit, integration and fixture-based parser tests
```

Responsibilities stay separated: crawler/source integration, normalization,
deduplication, job orchestration and API code each live in their own module, and
neither models nor views contain source-specific parsing logic.

## Domain model

**Locations are data.** `core.locations` holds a three-level hierarchy
(`Province -> City -> Region`) plus two mapping tables: `SourceLocation`, which
resolves each source's own place identifier (Divar's numeric place id,
Sheypoor's slug) onto that hierarchy, and `LocationAlias`, which maps the
normalised free-text place names found in listing text. Adding a city or a
source mapping is an insert, never a code change; crawler code contains no city
list. The hierarchy is deliberately shallow-but-extensible: sources frequently
publish only a province or only a neighbourhood, and *exactly one* level is
populated per mapping row (enforced by a database `CHECK` constraint). Regions
are curated lazily — the packaged seed covers all three provinces and their
main cities, with neighbourhoods seeded for the largest cities only.

`seed_locations` loads `core/locations/data/locations.json` idempotently
(create-or-update keyed on the stable `code`), so it is safe to run from a
deployment entrypoint and re-run after the data file changes. Rows are never
deleted: listings reference locations with `PROTECT`.

**Listings** (`core.listings`) store the normalized representation only.
Identity is `(source, source_id)` — the identifier the source itself uses —
never the URL, because sources rewrite URLs and one listing can be reached
through several of them. Money is stored in one canonical unit with an explicit
currency column, and a price that the source does not publish is `NULL` plus
`is_price_negotiable` where the source says "توافقی", never `0`. Listings keep
the raw source location text alongside the resolved hierarchy, and the last
source payload in `raw_data` for diagnostics. Availability is modelled as a
status column (`active` / `stale` / `delisted` / `hidden`) with an append-only
`ListingStatusEvent` log, so a listing that vanishes from a crawl is marked, not
deleted. Cross-source duplicate detection is intentionally *not* part of this
layer; it arrives in a later milestone.

## Sources

Only publicly accessible data is targeted. No authentication bypass, CAPTCHA
bypass, anti-bot evasion or private-data scraping is implemented, and each
source is handled according to its published restrictions.

| Source | Access notes (verified live) | Approach |
| --- | --- | --- |
| Divar | `divar.ir/robots.txt` and `api.divar.ir/robots.txt` allow all paths. The JSON API divar.ir's own web client uses: `POST /v8/postlist/w/search` returns 25 listings per page and `GET /v8/posts-v2/web/<token>` returns one detail document. Pagination is cursor-based: the response's `pagination.data` is sent back verbatim as `pagination_data` to obtain the next page, and crawling stops when `has_next_page` is false (verified: pages 1-3 share no listings). `/v5/*` answers 403 and is not used. Detail pages carry `seo.unavailable_after`, which later milestones read as an availability signal. | HTTP/JSON adapter, no browser |
| Sheypoor | `robots.txt` allows listing paths and `page_num` pagination and disallows `/search`, `/session`, `/pro` and bare query strings, all of which the adapter avoids: it only requests `/s/<slug>` and `?page_num=N`. Listings are embedded in the server-rendered Next.js React Flight stream (`self.__next_f.push` chunks, `<hex-id>:<payload>` rows with `"$id"` references), which the adapter rebuilds and resolves. Detail URLs are slugged — an id-only URL 404s — so `fetch_detail` requires the URL the listing was found at. No masked or private contact data is extracted. | HTTP adapter + SSR payload parsing, no browser |

Neither adapter sends credentials, bypasses access controls or extracts contact
details. Requests are paced by the configured per-source bucket, every HTTP
crawler call has a timeout, and permanent failures (401/403/404) are never
retried — see "Fault tolerance and pacing" below.

## Crawler reliability

- **Timeouts.** Every request carries a total timeout and a separate connect
  timeout (Divar 20 s / 5 s, Sheypoor 30 s / 5 s by default), both configurable.
- **Bounded retries with backoff.** At most `max_attempts` (4 by default) per
  request. Retryable: connection errors, timeouts, `408`, `425`, `429` and every
  `5xx`. Never retried: `401`, `403`, `404` and other `4xx`, nor a response that
  exceeds `MAX_RESPONSE_BYTES`. Backoff is exponential
  (`base * factor^(n-1)`, capped) with jitter.
- **`429`/`Retry-After`.** A `Retry-After` header (delta seconds or HTTP date)
  replaces the computed backoff; if it exceeds `MAX_RETRY_AFTER_SECONDS` the
  request fails loudly instead of sleeping for hours.
- **Rate limiting.** A token bucket per source (`REQUESTS_PER_SECOND` refilled,
  `BURST` capacity) that every attempt — including retries — passes through.
  Defaults are deliberately slow: one request every 2 s to Divar, every 3 s to
  Sheypoor. `InMemoryRateLimiter` is per process; `RedisRateLimiter` shares one
  bucket across workers and is the production default.
- **Observability.** Attempts, retries and give-ups are logged on the
  `north_estate.crawl` logger, and backoff sleeps are emitted as warnings so a
  crawl report can explain a slow run.
- **Testability.** Transport tests inject the clock and RNG, so retry, jitter
  and `Retry-After` behaviour is asserted without sleeping or touching a network.

## Key architectural decisions

- **HTTP-first crawling with a browser seam.** Both sources expose
  machine-readable data, so the default path is fast and deterministic and no
  adapter needs a browser today. The `Fetcher` protocol in
  `core/sources/transport.py` is the seam a Playwright-backed fetcher can slot
  into for sources that only render client-side, without touching adapters.
- **Fault tolerance lives in one transport, not in each adapter.** Timeouts,
  bounded retries, backoff, `Retry-After`, the response-size guard and pacing
  are written and tested once, so a new source inherits them by construction.
- **Adapters return source-shaped DTOs, never database rows.** Prices and dates
  stay exactly as the source printed them (`"۶,۹۵۰,۰۰۰,۰۰۰ تومان"`, Jalali
  dates); converting them is the normalization layer's job. This keeps parsing
  and semantic conversion independently testable and keeps crawler code out of
  the domain models.
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
