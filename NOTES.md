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

_In progress._

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
