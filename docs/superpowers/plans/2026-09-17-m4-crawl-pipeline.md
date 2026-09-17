# M4 — Crawl Pipeline: Jobs, Celery Worker + Beat, Observability

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A crawl never runs inside a request: an operator registers a `CrawlJob`
from a saved scope, a Celery worker claims it exactly once, the pipeline walks the
source (list pages -> details -> normalization -> persistence), and the job exposes
a terminal state, per-phase counters and a failure report.

**Architecture:** New `core/crawling` app owns job orchestration only. It resolves the
saved scope against reference data, drives an existing `SourceAdapter`, normalizes
through `core.normalization`, and writes through a small persistence service. Celery
+ Redis provides the worker and broker; a DB-backed `CrawlSchedule` plus a beat tick
task provide optional periodic crawls. Deduplication refinement and lifecycle sweeps
stay in M5 — M4 only guarantees the deterministic same-source `(source, source_id)`
upsert, which is what makes re-runs duplicate-free.

**Tech Stack:** Django 6, DRF, PostgreSQL, Celery 5 + Redis, `uv`, pytest / pytest-django.

**Spec:** `AGENTS.md` (Sections 6, 9, 10, 12, 13, 15) and `README.md` "Status" row 4.

## Global Constraints

- Crawler/source code stays out of models and views; orchestration lives in `core/crawling`.
- No new infrastructure beyond Celery + Redis (already declared in `pyproject.toml`).
- Same-source identity is `(source, source_id)`, never the URL.
- A listing is never deleted or silently dropped because it was not seen; M4 sets
  `last_seen_at`/`status=active` on sight and does **not** sweep for staleness (M5).
- Every test runs offline against fixtures/mocks; no live network, no real sleeps.
- New DB-touching tests carry `pytestmark = pytest.mark.integration`.

---

## Design Decisions (read before Task 1)

1. **Worker/beat split.** `run_crawl_job` runs on a worker; `dispatch_due_schedules`
   runs on a one-minute beat tick. Beat never performs HTTP itself.
2. **Claiming is atomic.** `claim_job(job_id)` uses `select_for_update(skip_locked=True)`
   and only accepts `pending`/`queued`, so redelivered tasks are no-ops and two workers
   cannot run the same job. This is the reason `config/settings/test.py` already insists
   on PostgreSQL.
3. **Per-listing failures are isolated; per-page failures stop the job.** One unparseable
   detail is counted and skipped; a list page that exhausts retries ends the crawl, and the
   job ends `partially_succeeded` (some pages committed) or `failed` (nothing committed).
4. **Property/transaction selection is honoured at the source where a slug is known, and
   recorded otherwise.** A new `SourceCategory` reference table (source + transaction +
   property -> external slug) is seeded from data, mirroring `seed_locations`. When a
   mapping exists, `CrawlScope.category` narrows the source request (verified Divar slugs:
   `apartment-sell`, `apartment-rent`, `shop-rent`). When it does not, the crawl runs
   place-wide and the job records the selection in its scope/report; out-of-selection
   listings are still persisted (they are real listings) but counted as
   `outside_requested_type`. No hardcoded category lists in crawler code.
5. **Observability is bounded.** Lifecycle transitions go to `CrawlJobEvent` rows; per-listing
   detail errors are aggregated in `CrawlJob.report['errors']` (deduped by `(source_id, type)`,
   capped) rather than written as unbounded rows.
6. **Beat is opt-in.** `CelerySchedule` rows are never seeded; with no rows, and
   `CELERY_BEAT_ENABLED=false`, no periodic crawl can start.

---

## File Structure

**Create**
- `config/celery.py` — Celery app, settings namespace `CELERY`, task autodiscovery.
- `core/crawling/__init__.py`, `apps.py`, `enums.py`, `models.py`, `admin.py`, `scope.py`,
  `persistence.py`, `runner.py`, `tasks.py`, `migrations/0001_initial.py`
- `core/crawling/management/commands/create_crawl_job.py` — register a job (and optionally enqueue).
- `core/crawling/management/commands/run_crawl_jobs.py` — worker-less inline drain for local dev.
- `core/sources/models.py` — `SourceCategory` reference table.
- `core/sources/migrations/0001_initial.py`, `core/sources/data/categories.json`,
  `core/sources/management/commands/seed_source_categories.py`
- `tests/crawling/conftest.py` + `test_models.py`, `test_scope.py`, `test_persistence.py`,
  `test_runner.py`, `test_tasks.py`, `test_schedule_dispatch.py`, `test_commands.py`

**Modify**
- `config/__init__.py` (expose `celery_app`), `config/settings/base.py` (+`CELERY_*`),
  `config/settings/production.py` (Redis already wired; nothing new unless a knob is added),
- `core/sources/config.py` or a new `core/sources/categories.py` for the resolver,
- `core/listings/enums.py` only if a job-status value is shared (it is not — job status is local),
- `README.md` (mechanism, lifecycle, commands, env vars).

---

### Task 1: `core/crawling` app, `CrawlJob` + `CrawlJobEvent`, admin

**Files**
- Create: `core/crawling/__init__.py`, `core/crawling/apps.py`, `core/crawling/enums.py`,
  `core/crawling/models.py`, `core/crawling/admin.py`, `core/crawling/migrations/__init__.py`
- Modify: `config/settings/base.py` (`LOCAL_APPS += ['core.crawling']`)
- Test: `tests/crawling/test_models.py`

**Interfaces**
- Produces: `CrawlJobStatus` (TextChoices: `pending`, `queued`, `running`, `succeeded`,
  `partially_succeeded`, `failed`, `cancelled`); `CrawlJob`; `CrawlJobEvent`.
- Produces: `CrawlJob.scope_province/city/region` (FKs, PROTECT, nullable, exactly one via
  `exactly_one_location_target()`), `scope_transaction_type`, `scope_property_type`,
  `source_external_id`, `source_category`, `page_limit`, `status`, counters (`pages_fetched`,
  `stubs_seen`, `details_fetched`, `listings_created`, `listings_updated`, `listings_skipped`,
  `errors`), `report`, `celery_task_id`, `error`, `requested_by`, timestamps.
- Produces: `CrawlJob.is_terminal`, `CrawlJob.mark_running()`, `.finish(status, report, error='')`.

- [ ] **Step 1: Write the failing model test** — create a job with a city scope, assert default
  `status == pending`, all money-free counters at 0, `report == {}`, and that creating a job with
  both a city and a region raises `IntegrityError` (the exactly-one-level CHECK).
- [ ] **Step 2: Run it** — `uv run pytest tests/crawling/test_models.py -v`; expect `ImportError`.
- [ ] **Step 3: Write the app, enums, models and migration**, reusing `LocationTargetMixin`
  from `core.locations.models` for the scope FKs, and `Source` from `core.sources.enums`.
  Add `CrawlJobEvent(job, from_status, to_status, level, message, context, created_at)` and an
  index on `(status, created_at)`.
- [ ] **Step 4: Register the app** in `INSTALLED_APPS` and run
  `uv run python manage.py makemigrations crawling`.
- [ ] **Step 5: Admin** — list/detail with counters and inline read-only events
  (`has_add_permission -> False`), mirroring `ListingStatusEventInline`.
- [ ] **Step 6: Re-run the test** — `uv run pytest tests/crawling/test_models.py tests/listings -v`; pass.
- [ ] **Step 7: Commit** — `git commit -m "M4: crawl job domain"`.

### Task 2: Scope resolution (`core/crawling/scope.py`)

**Files**
- Create: `core/crawling/scope.py`, `core/crawling/errors.py`
- Test: `tests/crawling/test_scope.py`

**Interfaces**
- Produces: `class ScopeResolutionError(SourceError)`.
- Produces: `build_scope(job) -> CrawlScope` — walks `province -> city -> region` (most specific
  first) through `SourceLocation`, returns a `CrawlScope(external_id=..., label=..., page_limit=job.page_limit, category=job.source_category or resolve_category(...))`.
- Uses: `core.locations.models.SourceLocation`, `core.sources.dto.CrawlScope`.

- [ ] **Step 1: Failing tests** — (a) a region-scoped job resolves the region's `SourceLocation`
  external id; (b) a city with no region mapping falls back to the city, then the province;
  (c) a scope with no `SourceLocation` row raises `ScopeResolutionError` naming the place and
  source; (d) `page_limit` is carried through.
- [ ] **Step 2: Run** — expect `ImportError`.
- [ ] **Step 3: Implement `build_scope`** with a level-ordered lookup:
  `[(Region, job.scope_region_id), (City, job.scope_city_id), (Province, job.scope_province_id)]`,
  taking the first `SourceLocation.objects.filter(source=...).filter(<level>=id)` hit.
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** — `git commit -m "M4: resolve crawl scope from reference data"`.

### Task 3: Source category reference data + resolver

**Files**
- Create: `core/sources/models.py`, `core/sources/migrations/0001_initial.py`,
  `core/sources/data/categories.json`,
  `core/sources/management/commands/seed_source_categories.py`, `core/sources/categories.py`
- Test: `tests/sources/test_source_categories.py`, `tests/sources/test_seed_categories_command.py`

**Interfaces**
- Produces: `SourceCategory(source, transaction_type, property_type, external_id, is_default)`
  with `UniqueConstraint(source, transaction_type, property_type)`.
- Produces: `resolve_category(source, transaction_type, property_type) -> str | None`.
- Data file shape: `{"divar": [{"transaction_type": "sale", "property_type": "apartment", "external_id": "apartment-sell"}, ...]}`.

- [ ] **Step 1: Failing tests** — resolver returns the seeded slug, `None` when unseeded, and
  the seed command is idempotent and rejects an unknown source.
- [ ] **Step 2: Run** — expect failure.
- [ ] **Step 3: Implement model + data-driven resolver + idempotent command** (same
  create-or-update-keyed-on-natural-key pattern as `seed_locations`).
- [ ] **Step 4: Seed only slugs verified against fixtures/live** and leave the rest out of the
  data file; a missing row must return `None`, never a guess.
- [ ] **Step 5: Run** — pass; `uv run python manage.py makemigrations sources`.
- [ ] **Step 6: Commit** — `git commit -m "M4: data-driven source category mapping"`.

### Task 4: Listing persistence (`core/crawling/persistence.py`)

**Files**
- Create: `core/crawling/persistence.py`
- Test: `tests/crawling/test_persistence.py`

**Interfaces**
- Produces: `@dataclass PersistOutcome(created: bool, reactivated: bool)`.
- Produces: `upsert_listing(normalized: NormalizedListing, *, raw: dict, image_urls=(), seen_at) -> PersistOutcome`.
- Consumes: `NormalizedListing` (`core.normalization.dto`), `Listing`, `ListingImage`, `ListingStatusEvent`.

- [ ] **Step 1: Failing tests** — (a) first write creates; (b) a second write with the same
  `(source, source_id)` but a changed title/price updates the same row, creates no duplicate,
  and advances `last_seen_at`; (c) `raw_data` keeps the last payload; (d) images are replaced
  by position without duplicates; (e) a `stale` listing seen again becomes `active` and appends
  a `ListingStatusEvent`; (f) different `source_id` -> new row.
- [ ] **Step 2: Run** — expect failure.
- [ ] **Step 3: Implement** inside `transaction.atomic()` with
  `select_for_update().get_or_create(...)`; update the normalized fields, `last_seen_at`,
  `last_checked_at`, `raw_data`; never touch `first_seen_at`; never delete.
- [ ] **Step 4: Run** — pass (integration marker).
- [ ] **Step 5: Commit** — `git commit -m "M4: idempotent listing upsert"`.

### Task 5: Crawl runner (`core/crawling/runner.py`)

**Files**
- Create: `core/crawling/runner.py`
- Test: `tests/crawling/test_runner.py` (uses `tests/sources` fixture helpers + a fake adapter)

**Interfaces**
- Produces: `@dataclass CrawlReport(pages, stubs, details, created, updated, skipped, failed, errors, outside_requested_type)`.
- Produces: `run_job(job, *, adapter=None, index=None, now=None) -> CrawlReport`.
- Consumes: `build_scope`, `get_adapter`, `LocationIndex.load`, `normalize_detail`, `upsert_listing`.

- [ ] **Step 1: Failing tests** with a `FakeAdapter` that yields two fixture list pages and a
  detail per stub: (a) counters match the fixtures; (b) re-running fills `listings_updated`
  and creates no new rows; (c) one `PermanentHTTPError` on a detail increments `failed`,
  does not abort, and the job ends `succeeded` unless *every* item failed; (d) a `SourceError`
  from `iter_list_pages` ends the job `partially_succeeded`/`failed` with the source error in
  `report['errors']`; (e) `outside_requested_type` counts listings that disagree with the job's
  requested property type without dropping them.
- [ ] **Step 2: Run** — expect failure.
- [ ] **Step 3: Implement the loop**:
  ```python
  for page in adapter.iter_list_pages(scope):
      counts.pages += 1
      for stub in page.items:
          counts.stubs += 1
          try:
              detail = adapter.fetch_detail(stub.source_id, url=stub.url)
              normalized = normalize_detail(detail, index=index)
              outcome = upsert_listing(normalized, raw=detail.raw, image_urls=detail.image_urls, seen_at=seen_at)
          except SourceError as exc:
              counts.failed += 1
              errors.record(stub.source_id, exc)
  ```
  Wrap `iter_list_pages` so a `SourceError` sets `report['stopped_reason']` and breaks.
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** — `git commit -m "M4: crawl runner with per-listing isolation"`.

### Task 6: Celery app, settings, `run_crawl_job` task, claiming

**Files**
- Create: `config/celery.py`, `core/crawling/tasks.py`
- Modify: `config/__init__.py`, `config/settings/base.py`, `config/settings/test.py`,
  `core/crawling/models.py` (add `claim_job`)
- Test: `tests/crawling/test_tasks.py`

**Interfaces**
- Produces: `config.celery.app` (Celery app, `config_from_object('django.conf:settings', namespace='CELERY')`, `autodiscover_tasks()`).
- Produces: `claim_job(job_id) -> CrawlJob | None` (atomic; `pending|queued -> running`).
- Produces: `run_crawl_job(job_id)` (`shared_task(bind=True, acks_late=True)`), returns a summary dict.

- [ ] **Step 1: Failing tests** — with `CELERY_TASK_ALWAYS_EAGER=True`: (a) running the task by
  id moves the job to a terminal status with counters; (b) running it twice leaves the second
  call a no-op and the counters unchanged; (c) `claim_job` on a terminal job returns `None`;
  (d) the task records `celery_task_id`.
- [ ] **Step 2: Run** — expect failure.
- [ ] **Step 3: Implement `config/celery.py`** and the settings block:
  `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND = redis_url()`, JSON serializers,
  `CELERY_TASK_ACKS_LATE=True`, `CELERY_WORKER_PREFETCH_MULTIPLIER=1`,
  `CELERY_TASK_TIME_LIMIT`/`CELERY_TASK_SOFT_TIME_LIMIT` from `env_str`, `CELERY_TIMEZONE=TIME_ZONE`.
- [ ] **Step 4: Implement `claim_job`** with `select_for_update(skip_locked=True)` inside
  `transaction.atomic()`, then `run_crawl_job` which claims, calls `run_job`, writes counters +
  `report`, transitions to `succeeded` / `partially_succeeded` / `failed`, and emits
  `CrawlJobEvent` rows.
- [ ] **Step 5: Run** — pass.
- [ ] **Step 6: Commit** — `git commit -m "M4: celery task and atomic job claiming"`.

### Task 7: DB-backed schedules + beat tick

**Files**
- Create: `core/crawling/models.py::CrawlSchedule` (+ migration), `core/crawling/schedules.py`
- Modify: `config/settings/base.py` (`CELERY_BEAT_SCHEDULE`, `CRAWL_SCHEDULE_TICK_SECONDS`,
  `CELERY_BEAT_ENABLED`), `core/crawling/tasks.py`
- Test: `tests/crawling/test_schedule_dispatch.py`

**Interfaces**
- Produces: `CrawlSchedule(source, scope_*, transaction_type, property_type, interval_minutes,
  is_enabled=False, last_run_at, next_run_at)`.
- Produces: `@shared_task dispatch_due_schedules()` — skips when `CELERY_BEAT_ENABLED` is false,
  claims due enabled rows with `select_for_update(skip_locked=True)`, creates a `CrawlJob` and
  enqueues `run_crawl_job`, advances `next_run_at`.

- [ ] **Step 1: Failing tests** — (a) a due enabled schedule creates exactly one job and advances
  `next_run_at`; (b) a disabled or future schedule creates none; (c) two dispatchers cannot run
  the same schedule twice (asserted by running the task twice and checking one job).
- [ ] **Step 2: Run** — expect failure.
- [ ] **Step 3: Implement model + dispatcher + `CELERY_BEAT_SCHEDULE` entry** guarded by
  `CELERY_BEAT_ENABLED` (default `False`), documented as opt-in.
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** — `git commit -m "M4: optional DB-backed periodic crawls"`.

### Task 8: Operator commands + engine wiring

**Files**
- Create: `core/crawling/management/commands/create_crawl_job.py`,
  `core/crawling/management/commands/run_crawl_jobs.py`
- Test: `tests/crawling/test_commands.py`

**Interfaces**
- Produces: `create_crawl_job --source divar --city sari --transaction sale --property apartment
  [--pages N] [--enqueue|--no-enqueue]` -> creates `CrawlJob`, prints id + status.
- Produces: `run_crawl_jobs [--once] [--job-id N]` -> claims and runs inline (dev without a worker).

- [ ] **Step 1: Failing tests** — command creates a `pending` job with the right scope/counters
  and rejects an unknown city; `run_crawl_jobs --once` with a fixture-backed adapter runs it to a
  terminal state; running again creates no duplicate listings.
- [ ] **Step 2: Run** — expect failure.
- [ ] **Step 3: Implement commands** as thin wrappers over `create_job` / `claim_job` / `run_job`
  (`--enqueue` is the default; `CRAWL_ENQUEUE_ENABLED=false` or `--no-enqueue` keeps dev runs
  worker-less).
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** — `git commit -m "M4: crawl job operator commands"`.

### Task 9: Observability polish + README

**Files**
- Modify: `core/sources/transport.py` (log lines carry `source` and job attribution where cheap),
  `core/crawling/runner.py`/`tasks.py` (final summary log on `north_estate.crawl`),
  `README.md`
- Test: `tests/crawling/test_runner.py` (caplog assertion), `tests/test_schema.py` untouched

- [ ] **Step 1: Add a failing assertion** that a finished job logs one summary line containing
  the job id, status, counters and duration, and that `CrawlJob.report` carries the same summary.
- [ ] **Step 2: Run** — fail; implement the structured summary; re-run.
- [ ] **Step 3: README** — document the Celery + Redis mechanism and why, the job lifecycle
  states, claiming, beat opt-in, the scope/category behaviour, exactly what "duplicate-free"
  means in M4 (same-source upsert; cross-source candidates are M5), how to run
  `celery -A config worker` / `celery -A config beat`, `create_crawl_job` / `run_crawl_jobs`,
  and the new env vars (`CELERY_*`, `CRAWL_SCHEDULE_TICK_SECONDS`, `CELERY_BEAT_ENABLED`).
- [ ] **Step 4: Run the full suite** — `uv run pytest` (offline, no browser, no live network).
- [ ] **Step 5: Commit** — `git commit -m "M4: crawl observability and docs"`.

---

## Verification Checklist (Definition of Done, Section 15 subset)

- [ ] `uv run pytest` passes with no live network and no real sleeps.
- [ ] A `CrawlJob` has an observable lifecycle in the DB (`pending -> running -> terminal`) and
      a failure reason + counters, never an opaque task.
- [ ] Redelivering `run_crawl_job` for a running/terminal job is a no-op.
- [ ] Re-running the same crawl creates zero duplicate `Listing` rows (`(source, source_id)`).
- [ ] Beat is inert unless `CELERY_BEAT_ENABLED=true` **and** a `CrawlSchedule` row exists.
- [ ] New `SourceCategory`/scope behaviour is data-driven; no city or category list in crawler code.
- [ ] README documents the mechanism, lifecycle, commands and env vars.

## Explicitly Out of Scope for M4

- Cross-source duplicate candidates and the staleness/delisting sweep (M5).
- API endpoints for creating/reading jobs (M6) — M4 exposes them via management commands.
- Dockerfile / docker-compose (M6).

---

## As Built (2026-09-17)

Shipped as planned, with these deviations recorded so this document stays honest:

- `claim_job`, `create_job`, `queue_job` live in `core/crawling/models.py` (no separate `schedules.py`);
  the beat dispatcher and both tasks live in `core/crawling/tasks.py`.
- `claim_job(job_id, task_id=...)` records the Celery task id as part of the
  `running` transition instead of a second save.
- The beat kill-switch moved out of the task and into `CELERY_BEAT_SCHEDULE`
  construction: beat and the worker are separate processes, so a task-level
  `CELERY_BEAT_ENABLED` check read the *worker's* environment. Found during live
  verification (the worker returned 0 for a due schedule).
- `resolve_source_place` walks the hierarchy (region -> its city -> its province),
  not just the job's own FK, so a region-scoped job can fall back to a city mapping.
- `SourceCategory` has no `is_default` column: an unmapped selection is a
  supported state, and removing the flag avoided untested behaviour.
- Live verification: beat -> dispatch -> worker -> real Divar crawl, 25 listings,
  0 failures, ~50 s at the configured 0.5 req/s.
