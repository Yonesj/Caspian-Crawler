# NorthEstate — Agent Guidelines

## 1. Project Overview

NorthEstate is a Django/PostgreSQL backend for crawling, normalizing, storing,
and exposing real-estate listings from public online sources in northern Iran.

Primary provinces:

- Mazandaran
- Gilan
- Golestan

Supported property categories include:

- Apartment
- House
- Villa
- Land
- Garden
- Rural house
- Commercial property / shop
- Other

The goal is **not** to build a complete commercial real-estate platform.

The goal is to demonstrate a backend system that is:

- runnable
- extensible
- fault-tolerant
- testable
- deployable
- architecturally defensible

The evaluation focuses especially on:

- architecture
- background processing
- duplicate-data handling
- fault tolerance
- rate limiting
- deployability
- test quality

Do not optimize primarily for HTML extraction complexity. A crawler that extracts fewer fields but sits inside a sound, well-tested architecture is worth more here than a fragile scraper with perfect field coverage.

---

## 2. Technology and Existing Setup

Required technologies:

- Python
- Django
- PostgreSQL
- Git

The choice of HTTP libraries, parsers, logging tools, and other dependencies is open — but explain the reasoning behind any significant choice in the README.

Current development environment:

- Python dependencies are managed with `uv`
- PostgreSQL is used as the development database
- Playwright is available for browser-based crawling
- Playwright browser binaries are stored in:
  `.playwright-browsers/`
- `PLAYWRIGHT_BROWSERS_PATH` points to:
  `/workspace/.playwright-browsers` when running inside the development
  container
- Tests use pytest and pytest-django
- API functionality uses Django REST Framework
- API schema/documentation uses drf-spectacular

Do not introduce additional major infrastructure or dependencies without
first considering whether the requirement can be satisfied with the existing
stack.


### Sandbox notes (read before assuming anything about Docker)
 
You are running inside an isolated development container that has **no
Docker access of its own** (no `docker` binary, no socket). This means:
 
- You can and should author the project's own `Dockerfile` /
  `docker-compose.yml` as deliverables — that's just writing files.
- You **cannot** run `docker compose up` yourself to test them. Don't spend
  time trying; note in the README that this needs to be verified outside
  the agent's own sandbox.
- Never assume a hardcoded `localhost` Postgres install. Database
  connection details (host, port, credentials) must come from environment
  variables (`DATABASE_URL` or Django's standard `DATABASES` settings,
  populated from `.env` in development). Treat wherever the dev database
  actually lives as an external dependency you connect to, not something
  you provision yourself.

When an important dependency or architectural choice is introduced, explain
the reason in the README.

---

## 3. Repository Structure

The existing project uses split Django settings:

- `config/settings/base.py`
- `config/settings/development.py`
- `config/settings/production.py`

Django applications must live at `core/`.

Keep responsibilities separated between:

- domain/data models
- API serializers and views
- crawler/source integrations
- crawling/job orchestration
- normalization
- deduplication
- infrastructure utilities

Do not put crawler-specific logic inside generic Django models or API views.

Before changing the structure, inspect the existing repository and preserve
working conventions unless there is a concrete architectural reason to change
them.

---

## 4. Crawler Architecture

The system must support multiple crawler sources.

Suggested sources include:

- Divar
- Sheypoor
- specialized/local real-estate websites
- other public sources where appropriate

The architecture must make adding another source possible without rewriting
the existing crawler system.

Crawler-specific logic must remain isolated from source-independent logic.

A crawler should conceptually separate responsibilities such as:

1. fetching
2. parsing/extraction
3. normalization
4. persistence
5. deduplication
6. crawl/job reporting

Do not make the system depend on a hardcoded list of cities inside crawler
logic.

Cities and regions must be represented as data so new locations can be added
without modifying crawler algorithms.

Only publicly accessible data should be targeted.

Do not implement:

- authentication bypass
- CAPTCHA bypass
- anti-bot evasion
- techniques intended to circumvent access controls
- scraping of private data

Each source must be handled according to its terms, technical restrictions,
and publishing policies.

The README must document:

- sources examined
- relevant access limitations
- implementation/architecture decision for each source

---

## 5. Crawl Reliability

Every HTTP crawler must use a defined timeout.

Retries must be:

- bounded
- limited to appropriate transient failures
- based on exponential backoff where appropriate
- aware of `Retry-After` when provided

`429 Too Many Requests` must be handled explicitly.

Do not retry indefinitely.

Do not automatically retry permanent errors such as:

- `401`
- `403`
- `404`

unless there is a specific, documented reason.

Temporary network failures and appropriate `5xx` responses may be retried
within defined limits.

Rate limiting must be deliberate and configurable rather than implemented as
uncontrolled request loops.

---

## 6. Background Jobs

Crawling must not depend on long-running synchronous HTTP requests from API
views.

The design must support registering a crawl job and observing its status.

A crawl job should have a clear lifecycle and failure state rather than being
treated as an opaque background task.

The background-processing mechanism is an implementation choice, but the
choice must be justified in the README.

Do not introduce distributed infrastructure merely for the sake of complexity.

---

## 7. Normalization

Different sources may represent the same concept differently.

Normalize source-specific data into a common listing representation before
exposing it through the main API.

Source-specific fields may be retained where useful, but consumers of the main
listing API should not need to understand every source's internal schema.

Normalization should cover, where applicable:

- property type
- transaction type
- province
- city/region
- title
- description
- price-related fields
- area
- source URL
- source identifier
- listing status
- timestamps

Because sources are Persian-language Iranian sites, normalization also needs
to handle, where encountered:
 
- Persian digits (۰–۹) in prices, areas, and phone numbers — convert to
  standard digits before storing numeric fields.
- Price units — Divar-style sources often mix Toman and Rial, and may
  present price as a range or as "توافقی" (negotiable/unspecified). Pick one
  canonical currency/unit for storage, record it explicitly, and represent
  "not specified" as an explicit null/flag rather than 0.
- Jalali (Solar Hijri) dates appearing on source pages — convert to
  Gregorian/UTC for storage; don't store raw Jalali strings as if they were
  sortable dates.
- City/province name variants — the same place may appear with different
  spellings or transliterations across sources; normalize against your data-
  driven city/region table (Section 4) rather than trusting source text
  verbatim.

Do not invent information that is not present in the source.

---

## 8. Duplicate Data

Deduplication is a core requirement.

A listing may:

- appear again in a later crawl of the same source
- appear through multiple pages or filters
- appear on multiple sources
- have a changed URL
- have a changed title while retaining substantially similar content

Do not rely solely on the URL as the identity of a listing.

The deduplication strategy must be explicit, deterministic where practical,
and covered by tests.

The system should distinguish between:

- the same listing encountered again
- an updated listing
- a genuinely different listing
- a similar listing from another source

False-positive deduplication is dangerous; do not aggressively merge listings
without evidence.

Document important deduplication decisions in the README.

---

## 9. Listing Lifecycle

The system must be able to represent what happens when a source listing is
deleted, deactivated, or otherwise becomes unavailable.

Do not silently delete local records merely because a listing was not observed
in one crawl.

The implementation should provide a clear way to represent listing
availability/status over time.

---

## 10. Required User Workflow

The system must support:

1. selecting a crawl source
2. selecting a geographical scope
3. selecting transaction type:
   - purchase
   - sale
   - rent
4. selecting property type
5. selecting a city or region
6. creating a crawl job
7. viewing crawl-job status
8. searching normalized listings
9. filtering normalized listings
10. re-running crawls without creating duplicate records
11. managing listing status when the source listing disappears or is disabled

---

## 11. API

Use Django REST Framework for the API.

Keep API code thin.

Business logic should not be buried inside serializers or views when it
belongs in a domain/service layer.

API filtering and search should operate on the normalized representation.

Use drf-spectacular to keep the API schema/documentation accurate.

When adding or changing an endpoint:

- add/update tests
- update schema documentation when necessary
- keep response semantics consistent
- avoid leaking source-specific implementation details unnecessarily

---

## 12. Testing

Use:

```bash
uv run pytest
```

Expectations:
 
- **Unit tests** for normalization and deduplication logic — these are the
  highest-value tests in this project (per Sections 7–8) and should not
  require a database or network access to run.
- **Integration tests** for API endpoints (via pytest-django + DRF's test
  client), covering the workflow in Section 10: creating a crawl job,
  reading its status, searching/filtering listings, and re-running a crawl
  without duplication.
- **Crawler/parser tests** must run against saved fixture HTML/JSON captured
  from each source, not live network calls. Never let the automated test
  suite depend on real sites being reachable or unchanged — that makes CI
  flaky and can itself become an unwanted extra load on the source.
- Tests that intentionally exercise retry/backoff/rate-limit logic should
  use a fake clock or mocked transport rather than real sleeps or real
  requests.
- Mark slow or optional tests distinctly (e.g. a pytest marker) so the
  default run stays fast; document how to run the full suite in the README.
---
 
## 13. Deployment
 
Deployability is one of the explicit evaluation criteria — treat it as a
first-class deliverable, not an afterthought.
 
The project should ship:
 
- a `Dockerfile` for the application itself
- a `docker-compose.yml` (or equivalent) that brings up the app, PostgreSQL,
  and whatever background-job infrastructure Section 6 requires, with a
  single command
- a documented way to run migrations and create any required initial data
  (e.g. seed cities/provinces) on first boot
- production settings (`config/settings/production.py`) that read secrets
  and connection details from environment variables — never hardcode
  credentials, and never commit a populated `.env`
Document in the README, concretely:
 
- the exact commands to bring the whole system up from a clean checkout
- which environment variables are required and what they configure
- how background job workers are started/monitored in this setup
As noted in Section 2, you (the agent) cannot execute `docker compose up`
inside your own sandbox — write these deliverables carefully and note in the
README that end-to-end container startup should be verified outside the
sandbox before considering this section done.
 
---
 
## 14. README Requirements (consolidated)
 
The README must include, at minimum:
 
- project overview and how to run it locally and via Docker (Section 13)
- required environment variables
- per-source notes: what was examined, access limitations, and the
  architectural decision made (Section 4)
- the background-processing mechanism chosen and why (Section 6)
- the deduplication strategy and key decisions (Section 8)
- how listing lifecycle/status is represented (Section 9)
- how to run tests, and what's covered vs. not (Section 12)
- any significant dependency or architectural choice not otherwise obvious
  from the code
---
 
## 15. Definition of Done
 
Before considering a milestone complete, check it against the evaluation
criteria directly:
 
- [ ] **Architecture** — crawler sources, normalization, dedup, and API are
      cleanly separated (Sections 3–4); adding a new source doesn't require
      touching unrelated code.
- [ ] **Background processing** — crawl jobs run asynchronously with an
      observable lifecycle and failure state (Section 6).
- [ ] **Duplicate-data handling** — dedup logic is explicit, tested, and
      documented (Section 8).
- [ ] **Fault tolerance** — timeouts, bounded retries, backoff, and
      `429`/`Retry-After` handling are all in place (Section 5).
- [ ] **Rate limiting** — per-source limits are configurable, not
      hardcoded loops (Section 5).
- [ ] **Deployability** — `docker-compose up` (verified outside the agent
      sandbox) brings up a working system from a clean checkout
      (Section 13).
- [ ] **Test quality** — unit tests for normalization/dedup, integration
      tests for the API workflow, and fixture-based crawler tests all pass
      without live network access (Section 12).