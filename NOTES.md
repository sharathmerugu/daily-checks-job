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
  before, 633 statements and 570 commits; after, **6 statements and 2 commits**. The number of
  SELECTs is fixed at three (datasets, checks, records) however many datasets, checks or records
  there are, and the owner comes from the dataset already loaded instead of a query per failure.
  The results are written with batched INSERTs (SQLAlchemy's insertmanyvalues), so the INSERT
  count still grows with the number of results, one statement per batch (about 1000 rows), not
  per result. `tests/test_job.py::test_job_statement_count_does_not_grow_with_records_or_checks`
  pins the SELECT count and the batching for runs that fit in one batch.
- **Behaviour check.** On the fixtures, the old job with only the two fixes applied and the
  new job store the same results (same check, record, passed, detail, in the same order) and
  send the same notifications in the same order.

### Unavoidable differences (transaction semantics)

- The old job committed after every result. The new job writes the run row first (committed,
  status `running`, as before), then all results and the `succeeded` status in **one
  transaction**. If an evaluator raises part-way, the job commits the results evaluated so far
  and re-raises, so, as before, those results are kept and the run stays `running`
  (`test_job_keeps_the_results_it_completed_when_an_evaluator_raises`). Per-record kinds are
  evaluated lazily for this, so the records judged before the failing value keep their results
  too. A crash of the process itself (killed, connection lost) loses the uncommitted results,
  where the old job had committed them one by one.
- Notifications are sent **after** the final commit, so an owner is never told about a result
  that was not stored. Before, a crash part-way left the owners of earlier datasets already
  notified; now no digest is sent for a run that did not finish.
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
even when a cycle leads back to it. At most five queries (run, dataset, a failure `EXISTS`, the
edges, the impacted datasets; four when nothing is downstream), however big the graph. I chose Python over a recursive CTE because
the graph here is small, the code is easier to read and test, and a CTE on a cyclic graph needs
path tracking that blows up on dense graphs. At scale see Part 4, question 2.

**Tests** (`tests/test_impact.py`): a chain (1, 2, 3 hops; unrelated dataset left out), a diamond
plus shortcut (each dataset once, fewest hops), a cycle including one back to the failed dataset,
nothing downstream (empty, and upstream datasets are not included), both 404s, the 409, and a query
count that does not grow with the graph. Also checked by hand on the seeded fixtures.

## Part 3: Add-a-check-kind skill

The skill is a Claude Code project skill: `.claude/skills/add-check-kind/SKILL.md`.

### How to run it

From the repository root, with Postgres up (`make up`, or just `docker compose up -d db` for
`uv run pytest`), start Claude Code and ask for the kind in plain words, for example:

```
claude
> Add a check kind called not_negative: a record passes when the value is a number >= 0.
```

Claude Code loads project skills from `.claude/skills/` at session start and picks this one from
its description; `/add-check-kind <name>: <rule>` invokes it explicitly. The file is plain
Markdown, so any other assistant (Codex, Cursor, ...) can be told "follow
`.claude/skills/add-check-kind/SKILL.md`". Headless: `claude -p "Use the add-check-kind skill to
add ..."`. Checked: a fresh `claude -p` session started in the repository lists
`add-check-kind` among both its skills and its slash commands.

### What it does

Pins down the inputs (name, rule, params) and makes the agent **decide and write down every edge
the rule leaves open** (missing/null, wrong types, equality between `1`/`1.0`/`"1"`/`true`,
case, whitespace, unhashable values, per-record vs whole-dataset). Then the five places from
`CONTRIBUTING.md`, in order, **tests first** (with the failures it should see), and ends with
`make test` (or `uv run pytest`) plus a job run on the fixtures. It finds code by grep and names
(`CheckKind`, `PARAMS`, `EVALUATORS`, `each_record`, `outcomes`), never by line numbers, and
names the traps a fresh agent falls into: `freshness` is used in a test as the example of an
*unknown* kind; `add_dataset` does not validate params; params are stored raw (model defaults
not applied); `kind` is at most 30 characters; evaluators must not query the database (a test
pins the query count) and must not raise.

### The uniqueness demonstration

I ran the skill once through a **fresh Claude Code subagent with no context** from this session
(only: kind name, the rule from the brief, and "use the add-check-kind skill; do not commit"). Its
output is committed unchanged in `4c53f4c`: an empty `UniquenessParams`; a whole-dataset
evaluator (a `Counter` keyed by `json.dumps(value, sort_keys=True)`); 7 check tests and 2
declaration cases; a `customer id unique` check on `raw_customers.customer_id` (the fixtures
already have `C0007` twice, so no records were changed); and a `docs/checks.md` section. It
watched the new tests fail (`unknown check kind 'uniqueness'`) before implementing, then ran the
full suite (43 passed) and the job on the fixtures (succeeded; exactly the two `C0007` records
fail). I re-ran both myself before committing.

Its decisions (tested and documented in `docs/checks.md`): every record sharing a value fails,
not only the later ones; missing/null fail as missing and are never duplicates of each other;
values compare strictly as JSON (`1`, `1.0`, `"1"`, `true` all differ); strings are case- and
whitespace-sensitive and `""` is a value (blankness is completeness' job); lists and objects
compare by content; detail `customer_id='C0007' is shared by 2 records`.

### Manual fixes after running it

- **To the generated code: none.** I reviewed the diff and found nothing to change.
- **To the skill** (`90071f2`, from the agent's own report of what was unclear):
  1. It said the new tests "must fail now", but the invalid-declaration cases pass before the
     kind exists (an unknown kind is rejected anyway). Now it says which tests should fail and
     with which error.
  2. It told the agent never to raise on bad values while `accuracy` and `timeliness` still do
     (kept on purpose in Part 1). Now it says so and tells the agent not to copy or change them.
  3. It suggested `json.dumps` only for lists and dicts; it works for every JSON value and
     already keeps `1`/`1.0`/`"1"`/`true` apart, so the skill now says that.
- Not a skill problem, but worth knowing: the subagent's Skill tool said "Unknown skill"
  because the skill file was created after this session started (it fell back to reading the
  file, as the prompt allowed). A fresh session, as reviewers will use, loads it normally.

**Independent reusability check:** I also tested the skill using a fresh Claude Code agent in an
isolated worktree, asking it to implement a different check kind (`pattern`, using regex
validation). The agent used only the repository and skill instructions, updated all five
required integration points, and completed the implementation without manual code changes. The
full test suite passed with 56 tests (43 existing and 13 new). I discarded the experimental
implementation afterward, leaving the assessment branch unchanged.

## Part 4: Written questions

**1. Faster, safe to rerun, able to resume.** *Faster:* the job already loads everything in
three queries and writes results in batches, but at scale it holds every record in memory and
evaluates in one process. I would stream records per dataset (server-side cursor, `yield_per`),
push simple per-record kinds into SQL where possible (completeness and range checks are a
`CASE` over JSONB in one `INSERT ... SELECT`), write results with `COPY`, and fan out one task
per dataset (the repo already has a Redis worker) since datasets are independent. *Safe to
rerun:* make a run unique per date (`UNIQUE (run_date)` on `runs`, the job does
`INSERT ... ON CONFLICT` and reuses the existing run instead of creating a second one), make
results unique per `(run_id, check_id, record_id)` and write them with `ON CONFLICT DO
NOTHING` (or delete-and-replace a dataset's results in one transaction), and record digests in
an outbox table keyed by `(run_id, owner)`: the digest row is written in the same transaction
as the results, a sender marks it sent, and a rerun never re-sends a row already marked sent.
The unique key stops a digest being *enqueued* twice, but not *delivered* twice: if the sender
crashes after the provider accepts the digest and before it marks the row sent, the row is sent
again. Where the email provider supports an idempotency key, send a stable one derived from
`(run_id, owner)` so the provider drops the repeat; otherwise delivery is at-least-once, and the
notes and the digest itself should say so (a rare duplicate digest, never a lost one).
*Resume:* track progress per `(run_id, dataset_id)` with a status (`pending`, `done`); each
dataset's results and its "done" mark commit together, so after a crash the rerun skips
finished datasets and redoes only the one that was in flight. Digests go out once every
dataset of the run is done (or per owner once their datasets are), driven from the outbox.

**2. Impact on a graph with millions of datasets and edges.** Precompute it. Keep a
transitive-closure table `downstream_of(ancestor_id, descendant_id, hops)` holding the fewest
hops for every reachable pair, with an index on `ancestor_id`; the endpoint becomes one indexed
lookup (`WHERE ancestor_id = :id ORDER BY hops`) plus the failure check. Lineage changes far
less often than it is queried, so maintain the table when edges change: adding edge `u -> v`
inserts `(a, d, h_a + 1 + h_d)` for every ancestor `a` of `u` (including `u`) and every
descendant `d` of `v` (including `v`), keeping the minimum; removal is harder (shortest paths
can lengthen), so recompute the affected ancestors' rows incrementally, or rebuild the table
in the background and swap it in. If the closure is too big (wide fan-out makes it quadratic),
fall back to caching per-dataset results keyed by a lineage version number, or run the BFS in a
graph store, but the precomputed table is the simplest thing that answers in milliseconds. Since
the result does not depend on the run, the same rows serve every run.

**3. Keeping the skill working as the code changes.** Make drift fail loudly in CI rather
than in a reviewer's session. (a) A guard test that the kinds agree everywhere:
`set(get_args(CheckKind)) == set(PARAMS) == set(EVALUATORS)`, that every kind has a section in
`docs/checks.md`, at least one fixture check and at least one test in `tests/test_checks.py`.
The skill's "done" list then has an objective check, and a code change that breaks the
five-places contract breaks the build. (b) The skill finds code by grep and by names
(`EVALUATORS`, `CheckKind`, `PARAMS`, `outcomes`), not line numbers, and says "follow what is
actually there" when the shape differs; keeping those names stable (or updating the skill in the
same PR that renames them) is part of review, via a CODEOWNERS entry on the skill. (c) A
scheduled CI job that runs the skill headless (`claude -p`) on a throwaway kind (for example
"`not_negative`: passes when the value is a number >= 0") on a fresh checkout, then runs `make
test` and the guard test, and throws the branch away; a failure means the skill and the code
have drifted. (d) Keep `CONTRIBUTING.md` the source of truth and have the skill read it first,
so a process change made in one place reaches the agent.

## How I used AI

- **Tool:** Claude Code (Opus) for the whole exercise, in my terminal, driven by two of my own
  skills: one for planning, one for implementing in small test-first slices. I reviewed every
  diff before committing and kept the commits small.
- **Discovery and planning:** three parallel read-only subagents (failing checks and job
  performance; digest and lineage integration points; check-kind integration points and skill
  design). I used their findings to write the plan, then approved and trimmed it: I dropped
  ideas outside the brief (idempotent reruns, checkpoints, extra endpoints) and kept them for the
  Part 4 answers.
- **Part 1:** tests first, then the fix and refactor; a throwaway script compared the old job
  (with only the two fixes) against the new one on the fixtures and counted statements and
  commits. Not committed.
- **Part 2:** tests written and watched failing before each change. One test I wrote had a
  setup bug (a duplicate lineage edge); the failure was an `IntegrityError` rather than the
  missing route, so I fixed the test before writing the endpoint. I tightened the 404 test
  because it passed before the route existed (FastAPI's own 404).
- **Part 3:** Claude drafted the skill from the discovery notes; I rewrote it once the Part 1
  refactor had changed the job (the first draft described an `if/elif` chain and asserted on
  `send_failure`, both gone). The uniqueness run was a fresh subagent, as described above.
- **Part 4 and these notes:** drafted with Claude from the decisions made along the way,
  edited by me.

## Time spent

About 2 hours.

## With more time

- Make bad values fail the record instead of aborting the run (`accuracy` range on a
  non-number, `timeliness` on an unparseable timestamp). I kept the existing behaviour because
  Part 1 asked for it, but it is the most likely cause of a run "failing partway through".
- The reliability work from Part 4 Q1: one run per date, unique results, a digest outbox,
  per-dataset progress.
- The guard test and scheduled skill run from Part 4 Q3.
- Remove `Notifier.send_failure`, now unused, once nothing else depends on it.
- For the impact query: an index on `results (run_id, passed)` for the failure check (only
  `run_id` is indexed today), and the closure table from Part 4 Q2 once the graph grows.
