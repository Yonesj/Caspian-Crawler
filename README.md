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
| 3 | Normalization: Persian digits, Toman/Rial, Jalali dates, locations | done |
| 4 | Crawl pipeline: jobs, Celery worker + beat, observability | done |
| 5 | Deduplication and listing lifecycle | done |
| 6 | API endpoints and complete operator/API documentation | done |
| 7 | Dockerfile and docker-compose deployment | planned |

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

# 4. Schema, reference data and an admin account
uv run python manage.py migrate
uv run python manage.py seed_locations           # idempotent; safe to re-run
uv run python manage.py seed_source_categories   # idempotent; source category slugs
uv run python manage.py createsuperuser

# 5. Run the API
uv run python manage.py runserver

# 6. Run a worker (in another shell) so crawl jobs start
uv run celery -A config worker -l info
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

## API

Listing and location reads are public. Creating or inspecting crawl jobs
requires a JWT access token; ordinary users can see only jobs they requested,
while staff users can see every job. Crawling is always queued for Celery and
never runs inside the HTTP request.

Obtain a token and pass it with the configured `JWT` prefix:

```bash
curl -X POST http://127.0.0.1:8000/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"operator","password":"your-password"}'

curl http://127.0.0.1:8000/api/crawl-jobs/ \
  -H 'Authorization: JWT <access-token>'
```

### Selection and listings

| Method and path | Purpose |
| --- | --- |
| `GET /api/crawl-options/` | Source, transaction and property-type choices |
| `GET /api/locations/provinces/` | Active provinces |
| `GET /api/locations/cities/?province=<id>` | Active cities, optionally under one province |
| `GET /api/locations/regions/?city=<id>` | Active regions, optionally under one city |
| `GET /api/listings/` | Paginated normalized listing search |
| `GET /api/listings/<id>/` | One normalized listing |

Anonymous listing queries are restricted to `active` rows, even if another
status is requested. Staff users may filter the full lifecycle with `status`.
The response includes the source identity and URL, normalized classification,
structured location and Toman price fields, physical attributes, lifecycle
timestamps and image URLs. It deliberately omits raw source payloads and
deduplication-review internals.

Exact filters are `source`, `transaction_type`, `property_type`, `province`,
`city`, `region`, `status` and `is_price_negotiable`. Range filters are
`min_area`/`max_area`, `min_sale_price`/`max_sale_price`,
`min_deposit`/`max_deposit` and
`min_monthly_rent`/`max_monthly_rent`. Use `search` for title/description and
`ordering` (prefix `-` for descending) with `published_at`, `first_seen_at`,
`last_seen_at`, `area_sqm`, `sale_price`, `deposit` or `monthly_rent`.

```bash
curl 'http://127.0.0.1:8000/api/listings/?transaction_type=sale&city=12&min_area=80&search=ساحل&ordering=-published_at&page=1'
```

### Crawl jobs

Create a job by selecting exactly one hierarchy level. Location IDs come from
the selection endpoints above; source-specific place and category identifiers
are resolved and snapshotted by the existing crawl service.

```bash
curl -X POST http://127.0.0.1:8000/api/crawl-jobs/ \
  -H 'Authorization: JWT <access-token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "source": "divar",
    "transaction_type": "sale",
    "property_type": "apartment",
    "page_limit": 2,
    "scope": {"city_id": 12}
  }'

curl http://127.0.0.1:8000/api/crawl-jobs/42/ \
  -H 'Authorization: JWT <access-token>'
```

`scope` accepts exactly one of `province_id`, `city_id` or `region_id`.
Creation returns `201` after registering and queueing the job; poll the detail
endpoint for status, counters, report/error, timestamps and its append-only
event history. Schedules, lifecycle sweeps and duplicate review remain operator
or Django-admin workflows rather than public mutation endpoints.

Swagger UI, ReDoc and the raw OpenAPI schema remain development-only. Their
routes are registered only when `DEBUG` is true; production exposes the API but
none of the documentation endpoints.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Required in production; must be a long random string |
| `DJANGO_SETTINGS_MODULE` | Settings module to load |
| `DJANGO_ADMIN_URL` | Admin path, default `admin/` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames (required in production) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins when deployed behind a separate HTTPS origin |
| `DATABASE_URL` | Full connection URL; alternative to the `POSTGRES_*` set |
| `POSTGRES_DB` / `_USER` / `_PASSWORD` / `_HOST` / `_PORT` | Individual connection settings |
| `POSTGRES_CONN_MAX_AGE` | Persistent connection lifetime in seconds |
| `REDIS_URL` | Shared Redis: rate-limit buckets, Celery broker/result backend and cache |
| `CRAWL_USER_AGENT` | User agent sent to crawl sources; production should carry a contact |
| `CRAWL_RATE_LIMIT_BACKEND` | `memory` (default) or `redis` (default in production) |
| `CELERY_TASK_TIME_LIMIT` / `CELERY_TASK_SOFT_TIME_LIMIT` | Per-crawl hard/soft limit in seconds (default 1800 / 1500) |
| `CELERY_BEAT_ENABLED` | `true` registers the periodic dispatch entry in Celery beat (default off) |
| `CRAWL_SCHEDULE_TICK_SECONDS` | How often beat asks for due schedules, in seconds (default 60) |
| `LISTING_SWEEP_ENABLED` | `false` disables the periodic lifecycle sweep (default on) |
| `LISTING_SWEEP_INTERVAL_SECONDS` | How often beat runs the sweep (default 3600) |
| `LISTING_STALE_AFTER_MISSES` | Misses in a row before a listing is `stale` (default 1) |
| `LISTING_DELISTED_AFTER_MISSES` | Misses in a row before it is `delisted` (default 3) |
| `LISTING_SWEEP_MIN_DETAILS` | Details a crawl must have persisted to count as evidence (default 1) |
| `DEDUP_CANDIDATES_ENABLED` | `false` disables the periodic candidate detection (default on) |
| `DEDUP_CANDIDATES_INTERVAL_SECONDS` | How often beat runs detection (default 86400) |
| `DEDUP_MAX_LISTINGS_PER_BUCKET` | Listings compared per `(transaction, city)` per run (default 500) |
| `CORS_ALLOWED_ORIGINS` | Comma-separated origins (production) |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | Opt-in TLS redirect and HSTS duration (production) |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD` | HSTS policy switches (default on; inert while duration is 0) |
| `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | Secure-cookie switches (default on in production) |

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
uv run pytest                     # default: fast, offline, no browser
uv run pytest tests/normalization # normalization unit tests (no database needed)
uv run pytest tests/sources       # crawler layer only (no database needed)
uv run pytest -m network          # opt-in checks against the live sources
uv run pytest -m playwright
```

Test markers: `integration` (database/API), `network` (real sources) and
`playwright` (browser binaries). The default run deselects the last two so CI
never depends on remote sites being reachable or unchanged.

Tests run against PostgreSQL, so the configured role needs `CREATEDB` to let
pytest-django create `test_<database>`. Without it, only non-database tests run.

Covered so far: authentication endpoints, development schema generation, the
public location selectors, normalized listing list/detail filtering and
search, active/staff visibility, authenticated crawl-job creation and
owner/staff visibility, and an API-driven crawl re-run that updates rather
than duplicates a listing; plus the location hierarchy and its integrity
constraints, the `seed_locations` command
(idempotency, dry-run, malformed input, source-id validation), the listing
model's identity, price, ordering and status-history rules, the whole crawler
layer — retry/backoff and `Retry-After` behaviour, both rate limiters, and both
source parsers — and the normalization layer: digit and letter folding, price
canonicalization, Jalali dates, category and title classification, attribute
extraction and location resolution, including end-to-end runs over the committed
fixtures, and the crawl pipeline: scope resolution, the idempotent
`(source, source_id)` upsert, partially failed crawls, the Celery task's
terminal states and redelivery no-op, the beat dispatcher and the operator
commands. The listing lifecycle is covered by the miss policy itself (one
miss marks `stale`, three mark `delisted`, `hidden` rows and out-of-scope
listings are untouched, a re-run never double-counts a miss, a dry run writes
nothing) and duplicate handling by the pure matcher (blockers, tolerances,
weighted signals, the score threshold) plus the review service (idempotent
detection, sticky human verdicts, `duplicate_of` linking, and the guarantee that
nothing is merged or deleted). Tasks run eagerly against an in-memory broker in
tests, so the default suite needs no Redis and no worker.

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
id/slug, `--category` scopes the crawl to one of the source's own categories
(needed to capture a sale or a rent detail deliberately), `--detail-only`
refreshes just the detail page, `--detail-index` picks which listing is also
captured in detail, and untrimmed copies go to the gitignored
`var/fixtures-raw/`. The manifest is merged rather than replaced, and each file
records the category it was captured under.

The committed Divar details cover both money shapes — `divar_detail_gar-qQRf`
(apartment sale, `قیمت کل`), `divar_detail_gas6SGcg` (apartment rent, `ودیعه` +
`اجارهٔ ماهانه`) and `divar_detail_gasGkf8r` (commercial rent) — and
`sheypoor_detail_464398666` covers a negotiable (`توافقی`) asking price with a
neighbourhood breadcrumb.

## Normalization

`core.normalization` is the only place that knows how one source's wording maps
onto the shared representation. It is pure: adapters hand it DTOs and it returns
a frozen `NormalizedListing`; nothing is written to the database (persistence is
the crawl pipeline's job) and nothing here touches the network.

- **Text.** Persian and Arabic-Indic digits are converted before numeric fields
  are parsed; display text only loses invisible directionality marks and
  whitespace runs, so a title is never rewritten. Matching keys (attribute
  labels, place names) are folded harder — Arabic `ي`/`ك` to Persian `ی`/`ک`,
  diacritics removed (`اجارهٔ` = `اجاره`), zero-width joiners dropped — which is
  the folding `LocationAlias` documents.
- **Money.** One canonical unit (Toman). `۳۰,۰۰۰,۰۰۰ تومان` becomes `30000000`;
  a Rial price is divided by ten; `میلیون`/`میلیارد`/`هزار` are applied; a range
  keeps its lower bound with the raw text retained. `توافقی` sets
  `is_price_negotiable` and stores no amount, and a published `0` (Divar's way
  of saying it has no price) is stored as NULL, never as zero. Text that cannot
  be read at all is logged and left NULL rather than guessed.
- **Dates.** Divar prints Jalali (`انتشار آگهی: ۲۶ شهریور ۱۴۰۵، ۲۳:۰۷`) and
  Sheypoor a naive Gregorian stamp; both are Tehran wall-clock, so both are
  converted to timezone-aware UTC. A stamp that cannot be parsed is NULL.
- **Classification.** Property type comes from the source's own category slugs
  (`apartment-sell`, `houses-apartments-for-sale`, `land`), matched on category
  tokens rather than a per-source table. Transaction type comes from the same
  slugs, falling back to the listing's title only when the category is silent
  (`فروش`, `اجاره`, `رهن`); a title that mentions both stays ambiguous. Anything
  unreadable is `unspecified`/`other` — a city-wide Divar crawl returns jobs and
  pets, and those are labelled as the non-property they are instead of being
  forced into a property category.
- **Locations.** The source's own place identifier wins (`SourceLocation`,
  matched through the seeded `source_ids`), then the printed place text against
  `LocationAlias` and the canonical names, most specific level first. The matched
  row's ancestors are filled in from the hierarchy; a place that is not in the
  reference data leaves all three foreign keys NULL rather than a partial guess.
  Divar's short-term/nightly rentals keep NULL amounts: a per-night rate is not
  representable in the monthly or total-price columns.

## Project layout

```text
config/settings/     # split settings: base / development / test / production
core/accounts/       # project user model and JWT endpoints
core/locations/      # province/city/region data, selectors + seed command
core/listings/       # normalized listings, filters, read API, status history
core/crawling/       # crawl jobs, job API, orchestration and Celery tasks
core/dedup/          # cross-source duplicate candidates, pure matcher, review
core/normalization/  # source DTOs -> normalized listings (pure, DB-free)
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
deployment entrypoint and re-run after the data file changes. Each level may
carry `source_ids` — the identifiers the sources themselves use, such as Divar's
`22` or Sheypoor's `nowshahr` for Sari and Nowshahr — which become
`SourceLocation` rows; the command refuses a file that reuses one source id for
two places. Coverage starts with the three provinces and the places the fixtures
touch; growing it is a data edit, not a code change (Divar publishes its own
city list at `GET https://api.divar.ir/v8/places/cities`). Rows are never
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
deleted; `consecutive_misses` counts the sweeps that did not see it. A reviewed
cross-source duplicate is recorded in `duplicate_of`, a nullable self-pointer
that links a discarded copy to the listing it duplicates. The link is metadata
only: neither row is merged, rewritten or removed.

## Sources

Only publicly accessible data is targeted. No authentication bypass, CAPTCHA
bypass, anti-bot evasion or private-data scraping is implemented, and each
source is handled according to its published restrictions.

| Source | Access notes (verified live) | Approach |
| --- | --- | --- |
| Divar | `divar.ir/robots.txt` and `api.divar.ir/robots.txt` allow all paths. The JSON API divar.ir's own web client uses: `POST /v8/postlist/w/search` returns 25 listings per page and `GET /v8/posts-v2/web/<token>` returns one detail document. Pagination is cursor-based: the response's `pagination.data` is sent back verbatim as `pagination_data` to obtain the next page, and crawling stops when `has_next_page` is false (verified: pages 1-3 share no listings). The category filter belongs under `search_data.form_data.data.category` — the shape the site's own breadcrumbs use — and is honoured (`city_ids: ["22"]` + `apartment-sell` returns 25 Sari apartments); the same body with a `filters.data.category` key returns HTTP 200 but ignores the filter, so it is not used. `/v5/*` answers 403 and is not used. Detail pages carry `seo.unavailable_after`, which later milestones read as an availability signal. | HTTP/JSON adapter, no browser |
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

## Background crawling

Crawling never happens inside a request. An operator registers a
`CrawlJob`, a worker claims it, and the job exposes its progress and outcome:

```bash
# register + publish (resolves and snapshots the scope before anything is queued)
uv run python manage.py create_crawl_job --source divar --city sari     --transaction sale --property apartment --pages 2

# worker + optional beat, in separate shells
uv run celery -A config worker -l info
CELERY_BEAT_ENABLED=true uv run celery -A config beat -l info

# development escape hatch: run pending jobs in-process, no worker needed
uv run python manage.py run_crawl_jobs
```

**Lifecycle.** `pending -> queued -> running -> succeeded | partially_succeeded
| failed | cancelled`, with every transition written to an append-only
`CrawlJobEvent`. A crawl that saved part of its scope before a source failed is
`partially_succeeded`, not `failed`; one that never reached the source is
`failed` with the typed error in `CrawlJob.error`. `CrawlJob.report` keeps the
final counters, the duration, the resolved place/category and a bounded,
deduplicated list of failures. Progress is also logged on the
`north_estate.crawl` logger.

**Claiming and idempotency.** `claim_job()` takes the job with
`SELECT ... FOR UPDATE SKIP LOCKED` and only accepts `pending`/`queued`, so two
workers can never run the same job and a redelivered `acks_late` message is a
no-op. Tasks carry a hard time limit so a stuck crawl cannot occupy a worker
forever. Within a run, one unparseable detail is counted and skipped; a list
page that exhausts the transport's retry budget stops the crawl.

**Scope is data.** A job stores the place the operator picked; the runner
resolves the source's own place id from `SourceLocation`, walking from the most
specific level up (region -> city -> province). The `(transaction, property)`
selection is resolved to a verified source category slug from `SourceCategory`
(`seed_source_categories`); when a mapping does not exist the crawl runs
place-wide and the job records that, rather than guessing a slug. An unmapped
place or a disabled source fails the job at creation time, before anything is
queued.

**Re-runs are duplicate-free** because persistence upserts on
`(source, source_id)` -- the source's own identifier, never the URL. A listing
seen again has its data refreshed and `last_seen_at` advanced, and one that
reappears after being `stale`/`delisted` is reactivated with a status event.
Cross-source duplicate candidates and the lifecycle sweep run next to this
pipeline rather than inside it (see below); nothing here deletes a listing.

**Periodic crawls are opt-in twice over.** Beat only has the dispatch entry
when `CELERY_BEAT_ENABLED=true`, and the dispatcher only acts on
`CrawlSchedule` rows that are enabled and due. No schedule rows are seeded, so a
fresh deployment never starts loading third-party sites on its own. The
dispatcher itself performs no HTTP; it creates jobs and lets workers crawl.
Note that beat and the worker are separate processes with separate
environments -- the flag belongs on the beat process.

## Listing lifecycle

A listing that stops appearing is aged, never deleted:

```bash
# report what ageing would happen, without writing
uv run python manage.py sweep_listings --dry-run
uv run python manage.py sweep_listings --job-id 12 --limit 5
```

**A miss is a finished crawl that should have seen the listing.** The sweep only
considers `succeeded` jobs that have not been swept yet, actually ran, and
persisted at least `LISTING_SWEEP_MIN_DETAILS` listings. For each of them the
in-scope listings are those from the same source, still `active`/`stale`,
matching the job's exact place and — when the job specified them — its
transaction and property type. Anything there whose `last_seen_at` predates the
run's `started_at` is charged one miss.

**Misses accumulate; one crawl never decides.** `consecutive_misses` increments
per sweep and the status walks `active -> stale -> delisted` after 1 and 3
misses (`LISTING_STALE_AFTER_MISSES`, `LISTING_DELISTED_AFTER_MISSES`). Every
transition is appended to `ListingStatusEvent` together with the job that caused
it. A listing seen again resets the counter and is reactivated. `hidden` is a
local decision and is never overwritten, and a crawl that persisted nothing or
observed no in-scope listing is skipped rather than read as "everything is
gone".

**It is safe to run often.** `CrawlJob.swept_at` records that a run has been
processed and rows are taken with `SELECT ... FOR UPDATE SKIP LOCKED`, so
re-running the command or running two workers cannot double-count a miss. The
task is never called from the crawl runner: it is a command,
`core.listings.tasks.sweep_listings` (hourly by default) and, like every
periodic entry, only scheduled when the beat process itself is enabled.

## Duplicate candidates

The same flat can be advertised on both sources with different URLs, titles and
photo sets. M5 records *candidates*; a human decides, and nothing is merged.

```bash
uv run python manage.py detect_duplicate_candidates --city sari --dry-run
uv run python manage.py detect_duplicate_candidates
```

**Detection is pure and conservative.** `core/dedup/matching.py` compares
fingerprints rather than rows — no database, no network, no clock — so the
riskiest logic in the project is tested as a plain unit test. A pair must first
clear the blockers (different sources, same transaction and property when both
are stated, same city/province when both resolve, neither row hidden or already
linked) and then collect at least two weighted signals scoring 50/100:

| Signal | Weight | Tolerance |
| --- | --- | --- |
| Area | 40 | within `max(3 m², 5%)` |
| Price | 30 | within 5% of the headline amount (sale price, else deposit, else rent) |
| Title | 20 | token-set Jaccard ≥ 0.5 after folding digits, letters and Persian stopwords |
| Published | 10 | within 3 days |

**Review, then link.** Candidates land in the Django admin, where two actions
confirm which side to keep and one rejects the pair. Confirming sets the
discarded listing's `Listing.duplicate_of` pointer and nothing else; rejecting a
previously confirmed candidate clears it. Re-running detection refreshes a
candidate's score and signals but never overwrites a reviewer's verdict, and
candidates are never deleted. Both rows always remain: the link says "this is a
copy of that", not "throw this away".

**It stays bounded.** Listings are bucketed by `(transaction, city)` and only
the most recently seen `DEDUP_MAX_LISTINGS_PER_BUCKET` rows per bucket are
compared, so a run stays close to linear in the listings we hold. Only listings
with a resolved city are compared; one whose place we could not resolve is left
alone rather than matched against a whole province.

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
  backs shared rate-limiting and throttle state across workers. Redis is the
  broker and result backend, so a worker needs no service beyond the one the
  shared rate limiter already uses. Jobs are claimed with
  `SELECT ... FOR UPDATE SKIP LOCKED`, which is why the suite runs on
  PostgreSQL.
- **Celery beat for optional periodic crawls**, driven by database-backed
  schedules. Beat is opt-in in its own settings and no schedules are seeded, so
  a fresh stack never begins crawling third-party sites by itself.
- **Source categories are reference data, not crawler code.** The slug a search
  endpoint expects for a `(transaction, property)` pair lives in
  `SourceCategory` and is seeded from a data file, mirroring `SourceLocation`.
  A missing mapping is a supported state -- the crawl runs place-wide and the
  job records the limitation -- so no slug is ever guessed in code.
- **Deduplication is two-layered and conservative.** Same-source repeats and
  updates are resolved deterministically from the source's own identifier, never
  from the URL. Cross-source similarity is scored by a *pure* matcher that needs
  two weighted signals and a 50/100 score before it records anything, and even
  then only a `pending` candidate for review: the system never merges listings
  automatically, because a false-positive merge is worse than a missed
  duplicate. The reviewer's decision is the only thing that sets
  `duplicate_of`, and it is metadata, not a rewrite.
- **Lifecycle is evidence-driven, not inference.** A listing ages only because
  specific finished crawls that should have seen it did not, and each of those
  runs can charge a listing at most one miss, once. Status is modelled over time
  (`consecutive_misses` plus an append-only `ListingStatusEvent`) instead of
  being collapsed into a delete, and a reappearing listing is reactivated rather
  than left `delisted`.
- **Money is stored in a single canonical unit (Toman)** with an explicit
  currency and flags for negotiable/unspecified prices; "not specified" is never
  stored as `0`. `price_currency` names the unit of the *stored* amount, so it is
  `IRT` for every row today: a price published in Rial is divided by ten and the
  original wording is kept in `raw_data`.
- **Normalization is a pure layer.** It converts adapter DTOs to a source-
  independent `NormalizedListing` with no database writes and no network access,
  so the highest-value tests in the project (digits, money, dates, category and
  place mapping) run as plain unit tests. The location index it resolves places
  against is built from the reference tables once per crawl and is constructible
  from plain data in tests.
- **Locations are data, not code.** Provinces, cities and each source's external
  location identifiers live in the database, so adding a city requires no code
  change.
