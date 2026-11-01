# Notes

## Setup

Under 10 minutes. Docker Desktop had to be started; after that `docker compose up -d db`
was enough to run the tests (against Postgres on port 55432, with `uv run pytest`).

## Part 1: Repair and refactor

### The two fixes

- **completeness** (`jobs/run_checks.py`, `completeness`): a value is blank when it is a string
  that is empty *or only whitespace* (`not value.strip()`). The old code only caught `""`.
- **timeliness** (`timeliness`): the reference time is 00:00 UTC on the run date (`time.min`).
  The old code used `time.max` (23:59:59.999999), so every record looked a day older.

### The refactor

- Each kind is one small function that judges one value and returns `""` (passed) or the
  failure detail. `EVALUATORS` maps a kind to its evaluator; one shared loop stores the
  results and collects the failures. The three copies of "store result, commit, look up
  owner, notify" are gone. `each_record` adapts a per-value rule to the evaluator signature
  (check, all of the dataset's records, run date), so a kind that needs to see the whole
  dataset (for example uniqueness) can be added without touching the loop.
- **Round trips.** Measured on the fixtures for 2026-11-03 (11 datasets, 23 checks, 568 results):
  before, 633 statements and 570 commits; after, **6 statements and 2 commits**, and the count
  no longer grows with datasets, checks or records. The job now makes three SELECTs (datasets,
  checks, records), inserts the results in batches (SQLAlchemy's insertmanyvalues), and uses
  the owner it already loaded instead of querying it per failure.
  `tests/test_job.py::test_job_round_trips_do_not_grow_with_records_or_checks` pins this.
- **Behaviour check.** On the fixtures, the old job with only the two fixes applied and the
  new job store the same results (same check, record, passed, detail, in the same order) and
  send the same notifications in the same order.

### Unavoidable differences (transaction semantics)

- The old job committed after every result. The new job writes the run row first (committed,
  status `running`, as before), then all results and the `succeeded` status in **one
  transaction**. If the job crashes part-way, the run stays `running` as before, but no
  partial results are left behind.
- Notifications are sent **after** that commit, so an owner is never told about a result that
  was not stored. Before, a crash part-way left the owners of earlier datasets already notified.
- Unchanged on purpose (the brief asks to keep behaviour): an unknown kind or a value an
  evaluator cannot handle (for example a non-numeric value in a range check, an unparseable
  timestamp) still raises and stops the run; re-running a date still creates a second run.

### Decisions on cases the rules leave open (each has a test in `tests/test_checks.py`)

- **Whitespace** means any whitespace Python's `str.strip()` removes (tabs, newlines too).
- **Blank applies to strings only.** `0`, `False` and empty lists are present values and pass
  completeness.
- **"No more than max_age_hours"** is inclusive: a timestamp exactly `max_age_hours` before
  00:00 UTC passes; one second older fails.
- **Timestamps without an offset** are read as UTC (kept from the old code).
- **Timestamps after the reference time** (later on the run date, or in the future) pass:
  they are not "more than max_age_hours before" it.

## Part 2: Digest and impact

### 2.1 Digest

- The job collects failures per owner while it evaluates, and after the commit calls
  `Notifier.send_digest(owner, run_date, failures)` once per owner. `send_failure` is no
  longer called (left in `Notifier`, unused).
- **One digest per owner, not per dataset**: an owner of several datasets gets one message
  listing the failures of all of them (each `Failure` names its dataset).
- **Owners with no failures get no digest.** The brief says the digest lists failures; an
  empty "all clear" message every day would be noise. Easy to add if wanted.
- Failures inside a digest keep the evaluation order (dataset id, check id, record id), so
  messages are stable from run to run.
- Tests (`tests/test_job.py`): the old one-message-per-failure test now asserts one digest
  with both failures and no `send_failure` calls; new tests cover one owner with two datasets
  (one digest) alongside a second owner, and an owner with no failures (no digest).

### 2.2 Impact

`GET /runs/{run_id}/datasets/{dataset_id}/impact` (`app/main.py`, `dataset_impact`).

**Response shape** (200):

```json
{"run_id": 1, "dataset_id": 1,
 "impacted": [{"dataset_id": 4, "name": "stg_customers", "owner": "ana@example.com", "hops": 1},
              {"dataset_id": 8, "name": "customer_ltv", "owner": "dan@example.com", "hops": 2}]}
```

- Echoes the run and dataset so the response stands on its own. Each impacted dataset carries
  its id (to follow up with other endpoints), name, **owner** (the people to warn are the
  point of an impact query) and `hops`. Sorted by `(hops, name)`: nearest first, stable order.
- A failed dataset with nothing downstream returns 200 with `"impacted": []`.

**Status codes**

- **404** when the run or the dataset does not exist (detail names which one), matching
  `/runs/{run_id}/results`.
- **409** when both exist but the dataset had no failures in that run. The brief defines impact
  only for a dataset that failed; returning an empty list would be indistinguishable from "failed,
  but nothing is built from it", and 404 would wrongly suggest the run or dataset is missing.
  409 says the request is valid but does not apply to the current state of that run.

**Where the traversal runs:** in Python, after one query that loads every lineage edge
(`downstream_hops`, a breadth-first search). BFS reaches each dataset first along a shortest
path, so `hops` is the fewest; a visited set keeps each dataset once and stops cycles (the
fixtures have one: `churn_scores` <-> `customer_segments`). The failed dataset itself is left out,
even when a cycle leads back to it. Five queries in total (run, dataset, a failure `EXISTS`, the
edges, the impacted datasets), however big the graph. I chose Python over a recursive CTE because
the graph here is small, the code is easier to read and test, and a CTE on a cyclic graph needs
path tracking that blows up on dense graphs. At scale see Part 4, question 2.

**Tests** (`tests/test_impact.py`): a chain (1, 2, 3 hops; unrelated dataset left out), a diamond
plus shortcut (each dataset once, fewest hops), a cycle including one back to the failed dataset,
nothing downstream (empty, and upstream datasets are not included), both 404s, the 409, and a query
count that does not grow with the graph. Also checked by hand on the seeded fixtures.

## Part 3: Add-a-check-kind skill

_In progress._

## Part 4: Written questions

_To do._

## How I used AI

- Claude Code (Opus) throughout, driven by two of my own skills: one for planning
  (three parallel read-only subagents: failing checks and job performance; digest and lineage
  integration points; check-kind integration points and skill design), one for implementation.
- Part 1: tests first (watched the new tests fail for the expected reasons), then the fix and
  refactor; a throwaway script compared the old job (with only the two fixes) against the new
  one on the fixtures and counted statements and commits.

## Time spent

_To fill in at submission._

## With more time

_To fill in._
