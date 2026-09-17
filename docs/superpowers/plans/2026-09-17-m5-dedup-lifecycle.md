# M5 — Deduplication and Listing Lifecycle

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A listing that disappears from a source stops pretending to be available,
and a listing that shows up on a second source is linked to the first one for
human review — deterministically, without ever merging or deleting a row.

**Architecture:** Two pure-ish services on top of the M4 pipeline. The lifecycle
sweep (`core/listings/lifecycle.py`) reads finished `CrawlJob`s and advances
`Listing.status` through `active -> stale -> delisted`, recording every change in
the existing `ListingStatusEvent` log and counting misses in
`Listing.consecutive_misses`. Deduplication (`core/dedup/`) scores cross-source
pairs with a pure matcher (`matching.py`) and stores *candidates*
(`DuplicateCandidate`) that a human confirms or rejects in the admin; confirming
sets a nullable `Listing.duplicate_of` pointer and nothing else. Neither service
talks to a source, and neither is called inline from the crawl runner: both are
commands, Celery tasks and (opt-in) beat entries.

**Tech Stack:** Django 6, DRF, PostgreSQL, Celery 5 + Redis, `uv`, pytest / pytest-django.

**Spec:** `AGENTS.md` (Sections 8, 9, 10, 12, 15), `README.md` "Status" row 5, and the
M4 plan at `docs/superpowers/plans/2026-09-17-m4-crawl-pipeline.md`.

## Global Constraints

- Crawler/source code never enters models or views; both new modules are domain services.
- Matching logic is **pure**: no database, no network, no clock — it takes fingerprints.
- Nothing merges listings, nothing deletes listings, nothing touches a source.
- The sweep only ever moves `active -> stale -> delisted`; `hidden` is a local decision
  and is never overwritten, and `duplicate_of` links never change a status.
- Every test runs offline against fixtures/mocks; new DB-touching tests carry
  `pytestmark = pytest.mark.integration`.
- Beat stays opt-in: the M5 periodic entries exist only when `CELERY_BEAT_ENABLED=true`
  *and* the feature flag is on.

## Design Decisions (read before Task 1)

1. **A miss is a finished crawl that should have seen the listing.** Eligible jobs are
   `succeeded`, not yet swept, have `started_at`, and fetched at least
   `LISTING_SWEEP_MIN_DETAILS` details (a crawl that persisted nothing cannot be trusted
   to distinguish "source empty" from "source broken"). Eligible listings are in the
   same source, `active`/`stale`, match the job's place exactly and match
   transaction/property when the job specified them, with `last_seen_at < started_at`.
   Such a crawl also has to have observed at least one in-scope listing.
2. **Misses are counted, not inferred from one crawl.** `consecutive_misses` increments
   per sweep; `1` miss marks `stale`, `3` in a row marks `delisted` (both configurable).
   Seeing a listing again resets the counter to `0`, including the M4 reactivation path.
3. **The sweep is idempotent by construction.** `CrawlJob.swept_at` is written inside the
   same transaction as the listing updates and jobs are locked with
   `select_for_update(skip_locked=True)`, so re-running the command or running two
   workers never double-counts a miss.
4. **Candidates are conservative evidence, not verdicts.** A pair must pass the blockers
   and reach at least 2 weighted signals with a score of 50/100 before a
   `DuplicateCandidate` is written. Candidate detection never sets `duplicate_of`.
   Confirmed/rejected decisions are sticky: re-detection refreshes the score and the
   signals of an already-reviewed pair but never rewrites the human verdict.
5. **`duplicate_of` is metadata.** The loser keeps its data, its status and its history;
   the pointer only records which row the duplicate is a copy of.
6. **Only resolved-city listings are compared.** Bucketing by `(transaction, city)` keeps
   detection near-linear and avoids matching a neighbourhood against a whole province.

## File Structure

**Create**
- `core/listings/lifecycle.py` — sweep policy, eligibility, miss counting.
- `core/listings/tasks.py` — `sweep_listings_task` (flag-gated).
- `core/listings/management/commands/sweep_listings.py` — operator entry point.
- `core/dedup/__init__.py`, `apps.py`, `enums.py`, `models.py`, `admin.py`, `matching.py`,
  `services.py`, `tasks.py`, `migrations/0001_initial.py`.
- `core/dedup/management/commands/detect_duplicate_candidates.py`.
- `tests/dedup/` (`__init__.py`, `test_matching.py`, `test_services.py`, `test_commands.py`).
- `tests/listings/test_lifecycle.py`, `tests/listings/test_sweep_command.py`.

**Modify**
- `core/listings/models.py` — `Listing.duplicate_of` (self-FK, `SET_NULL`) and
  `Listing.consecutive_misses`, plus a "not its own duplicate" check; regenerate migration.
- `core/crawling/models.py` — `CrawlJob.swept_at`.
- `core/crawling/persistence.py` — a seen-again listing resets `consecutive_misses`.
- `config/settings/base.py` — `LISTING_*` and `DEDUP_*` settings + gated beat entries.
- `README.md` — status row, lifecycle and deduplication sections, env vars.

---

### Task 1: Listing lifecycle fields and the sweep service

**Files**
- Modify: `core/listings/models.py`, `core/crawling/models.py`, `core/crawling/persistence.py`
- Create: `core/listings/lifecycle.py`
- Test: `tests/listings/test_lifecycle.py`

**Interfaces**
- Produces: `SweepPolicy(stale_after_misses, delisted_after_misses, min_details)` with
  `SweepPolicy.from_settings()`; `sweep_listings(*, policy=None, job_id=None, limit=None,
  dry_run=False, now=None) -> SweepResult`.
- Produces: `Listing.consecutive_misses` (positive small int, default 0) and
  `CrawlJob.swept_at` (nullable timestamp).

- [ ] **Step 1: Write failing tests** — a miss marks `active -> stale` and logs a
  `ListingStatusEvent`; a second and third miss reach `delisted`; a `hidden` listing and a
  listing in another city are untouched; a crawl that observed nothing is skipped; a job
  is swept once; `dry_run` writes nothing; a reappearance resets the counter.
- [ ] **Step 2: Run them** — `uv run pytest tests/listings/test_lifecycle.py -v`; expect failures.
- [ ] **Step 3: Add the fields, migration and service**, reusing `location_target()` and
  `ListingStatusEvent`.
- [ ] **Step 4: Run** `uv run pytest tests/listings tests/crawling -v`; pass.
- [ ] **Step 5: Commit** — `git commit -m "M5: listing lifecycle sweep"`.

### Task 2: Sweep command and Celery task

**Files**
- Create: `core/listings/tasks.py`, `core/listings/management/commands/sweep_listings.py`
- Modify: `config/settings/base.py`
- Test: `tests/listings/test_sweep_command.py`

- [ ] **Step 1: Write failing tests** — the command reports counts and supports
  `--job-id`, `--limit` and `--dry-run`; the task is inert when
  `LISTING_SWEEP_ENABLED=false`; the beat entry only exists when beat is enabled *and*
  the feature flag is on.
- [ ] **Step 2: Implement** the command and task, then wire the settings.
- [ ] **Step 3: Run** `uv run pytest tests/listings -v`; pass.
- [ ] **Step 4: Commit** — `git commit -m "M5: sweep command and periodic task"`.

### Task 3: `core/dedup` app and the pure matcher

**Files**
- Create: `core/dedup/{__init__,apps,enums,models,admin}.py`, `core/dedup/matching.py`, migration.
- Modify: `config/settings/base.py` (`LOCAL_APPS`).
- Test: `tests/dedup/test_matching.py`

**Interfaces**
- Produces: `DuplicateStatus` (`pending`/`confirmed`/`rejected`), `DuplicateCandidate`,
  `ListingFingerprint`, `DedupPolicy`, `match_pair(left, right, policy) -> DuplicateMatch | None`,
  `blockers(left, right) -> list[str]`.
- `DuplicateCandidate` has a unique ordered pair (`left_id < right_id` enforced by a check),
  a score, `signals`, a nullable `canonical` (`left`/`right`), `reviewed_by`/`reviewed_at`/`note`.

- [ ] **Step 1: Write the failing pure tests** — identical apartments match; a price far
  outside tolerance does not; a different transaction/property/city is blocked; a single
  signal below the score threshold is not a match; title Jaccard ignores Persian
  stopwords and digit spelling.
- [ ] **Step 2: Implement the app and matcher**, then `makemigrations dedup`.
- [ ] **Step 3: Run** `uv run pytest tests/dedup/test_matching.py -v`; pass.
- [ ] **Step 4: Commit** — `git commit -m "M5: duplicate candidate model and matcher"`.

### Task 4: Candidate detection service, command and review actions

**Files**
- Create: `core/dedup/services.py`, `core/dedup/tasks.py`,
  `core/dedup/management/commands/detect_duplicate_candidates.py`
- Modify: `core/dedup/admin.py`, `config/settings/base.py`
- Test: `tests/dedup/test_services.py`, `tests/dedup/test_commands.py`

- [ ] **Step 1: Write failing tests** — detection stores one candidate per pair and is
  idempotent; a re-run refreshes the score but keeps a confirmed/rejected verdict;
  confirming links the loser with `duplicate_of` and never deletes or merges; rejecting a
  confirmed candidate clears the pointer; `--dry-run` writes nothing; the task honours
  `DEDUP_CANDIDATES_ENABLED`.
- [ ] **Step 2: Implement** the service, the command, the admin actions and the task.
- [ ] **Step 3: Run** `uv run pytest` (full suite, offline) and update the README.
- [ ] **Step 4: Commit** — `git commit -m "M5: duplicate candidate detection and review"`.

## Verification Checklist

- [ ] `uv run pytest` is green, fast and offline (no Redis, no network required).
- [ ] `uv run python manage.py makemigrations --check --dry-run` reports no missing migration.
- [ ] The default suite still passes with `REDIS_URL` unset.
- [ ] README documents the miss policy, the candidate policy and the two new commands.
- [ ] Nothing in the M5 code deletes a listing or performs HTTP.

## As Built

_(filled in after implementation)_

---

## As Built (2026-09-17)

Shipped as planned, with these deviations recorded so this document stays honest:

- The shared fixtures (`places`, `source_categories`, `job_factory`) moved from
  `tests/crawling/conftest.py` to `tests/conftest.py` so the lifecycle and dedup
  suites start from the same hierarchy; that conftest now holds only the adapter
  doubles.
- The empty-crawl guard has two layers: a job below `LISTING_SWEEP_MIN_DETAILS`
  is not eligible at all, and an eligible job that observed no in-scope listing
  is recorded as skipped (and marked swept) instead of ageing anything. Both are
  covered by tests, including one that sets `min_details=0` to exercise the
  second layer.
- Skipping a job still writes `swept_at`: a crawl that told us nothing must not
  be re-evaluated on every sweep.
- Beat gating became a testable `build_beat_schedule(...)` function in
  `config/settings/base.py`; the entries still only exist when
  `CELERY_BEAT_ENABLED=true`. The two new feature flags default to **on**,
  because beat itself is already the opt-in and both tasks only touch our own
  database — an operator who enabled beat for crawl schedules can turn either
  one off with a single variable.
- The title signal's weight scales with the Jaccard score (`round(20 * j)`), so
  a barely-similar title contributes little; the minimum of two signals and a
  score of 50/100 still gates the pair.
- Detection buckets by `(transaction, city)` and compares only listings with a
  resolved city, and it summarises each listing's money as one headline amount
  (sale price, else deposit, else rent) for the price signal.
- `Listing.duplicate_of` and `Listing.consecutive_misses` needed two extra
  listings migrations because the dedup task landed after the sweep task; the
  `crawling` and `dedup` apps each got one.
- Live verification against the development database: `migrate` applied all four
  migrations, `sweep_listings --dry-run` selected the one eligible job, and a
  scripted run inside a rolled-back transaction created a synthetic Sheypoor copy
  of a real Divar listing, matched it at score 100 (`area, price, title,
  published`), confirmed the link (`duplicate_of`) and rejected it again without
  merging or deleting anything (`detect_duplicate_candidates` alone found no
  candidates in the 25 real single-source listings).
