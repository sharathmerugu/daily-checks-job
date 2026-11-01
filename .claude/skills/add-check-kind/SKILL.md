---
name: add-check-kind
description: Add a new data-quality check kind to this checks service end to end, following CONTRIBUTING.md - declaration (params model), evaluation in the daily job, fixture, tests and docs - and finish by running the tests. Use when asked to "add a check kind", "add a <name> check", "support a new kind of check", or "make checks able to verify <rule>".
---

# Add a check kind

A check kind is a rule applied to one `field` of the records of a dataset. The daily job
(`jobs/run_checks.py`) stores one result per record and check: passed, plus a `detail` saying
why it failed. `CONTRIBUTING.md` ("Adding a check kind") lists the five places a kind touches;
this skill does them in that order, with the tests written first.

Find code by **grep, not line numbers**: the files change. Copy the shape of the closest
existing kind rather than inventing a new style.

## 0. Pin down the inputs

You need three things. Take them from the request; ask only for what is missing and cannot
be decided sensibly. Do not invent a rule.

1. **Kind name.** snake_case, at most 30 characters (`checks.kind` is `String(30)` in
   `app/models.py`). It must not already exist:
   `grep -n "CheckKind" app/declarations.py`.
   Then check no test uses that name as the example of an **unknown** kind:
   `grep -rn '"<name>"' tests/`. (`tests/test_declarations.py` rejects `{"kind": "freshness"}`
   because freshness is not a kind. If your kind is that name, change that test's example to
   another unused name and say so in your summary.)
2. **Rule**, as one sentence: "A record passes when ...".
3. **Params**: names, types, required or optional, defaults, and what is invalid (empty list,
   zero or negative number, bad regex, mutually exclusive params...). "None" is a valid answer.

Then **decide every edge the rule leaves open and write the decisions down** (you will test
each one and put them in the docs). At least:

- **Missing field or `null`**: every existing kind fails with `f"{check.field} is missing"`.
  Do the same unless the rule clearly says otherwise.
- **Wrong-type values** (a string where a number is expected, an unparseable timestamp, a
  dict or list where a scalar is expected): fail the record with a detail; **never raise**. An
  exception aborts the whole run for every dataset. (Some existing kinds still raise on such
  values; that is known and out of scope. Do not copy it, and do not change them.)
- **Per record or per dataset?** A rule that compares a record with the others (uniqueness,
  "at most N rows per value", ...) needs every record of the dataset; see step 4.
- **Equality and types**: is `1` the same as `1.0` or `"1"`? Is `True` the same as `1`
  (in Python it is, and `bool` is a subclass of `int`)? Is matching case-sensitive? Are
  leading or trailing spaces significant? Prefer the strict, literal reading (values equal as
  JSON values, same type) unless the rule says otherwise, and state it.
- **Unhashable values** (lists, dicts) if you group or count values: they cannot be dict keys.

If anything material is ambiguous, restate rule, params and decisions in 3 to 5 lines before
coding; otherwise proceed and report the decisions at the end.

## 1. Read before writing

Read all of `CONTRIBUTING.md`, not only its "Adding a check kind" section: the rest sets
conventions (style, tests, commits) that apply here too.

```bash
cat CONTRIBUTING.md
cat docs/checks.md
grep -n "CheckKind\|PARAMS\|class .*Params" app/declarations.py
grep -n "^Evaluator\|^Rule\|def each_record\|^def \|EVALUATORS" jobs/run_checks.py
grep -n "^def " tests/test_checks.py tests/test_declarations.py
```

What you should find (if the code has moved on, follow what is actually there):

- `app/declarations.py`: one pydantic params model per kind (`extra="forbid"`), a `CheckKind`
  `Literal`, and a `PARAMS` dict from kind to model. `CheckKind` and `PARAMS` are separate:
  update both.
- `jobs/run_checks.py`: an `EVALUATORS` dict from kind to evaluator. An evaluator is
  `(check, records, run_date) -> Iterable[str]` (a list is fine): it gets every record of the
  check's dataset, in id order, and returns **one detail per record, in the same order**: `""` for a pass, otherwise
  why it failed. `each_record(rule)` turns a per-value rule `(check, value, run_date) -> str`
  into an evaluator. The shared loop stores results and sends owners their digests; **do not
  touch the loop**, and do not query the database from an evaluator (a test pins the job's
  query count).
- `tests/test_checks.py`: the `outcomes(session, kind, field, values, params)` helper runs
  one check over records whose field takes each value (`...` leaves the field out) and returns
  `{record_key: passed}`.

## 2. Tests first

Write the tests, run them, and see them **fail for the right reason** (the kind is not
declared / not evaluated), not an import or syntax error.

**`tests/test_checks.py`**, next to the other kinds (use the `session` and `notifications`
fixtures and the existing `outcomes` helper; name tests `test_<kind>_...`):

- one passing and one failing record;
- missing field (`...`) and `None`;
- one test per decision from step 0 (wrong type, equality, case, etc.);
- one test asserting the failure `detail` text, read from the stored result:

```python
from app.models import Record, Result  # already imported at the top of the file


def test_<kind>_detail_names_the_field_and_value(session, notifications):
    outcomes(session, "<kind>", "<field>", {"bad": <failing value>, "ok": <passing value>}, {<params>})
    details = dict(session.execute(
        select(Record.key, Result.detail).join(Result, Result.record_id == Record.id)
    ).all())
    assert details == {"bad": "<field>=<value!r> <why>", "ok": ""}
```

`add_dataset` (in `tests/conftest.py`) stores params **without validating them**, so the
params you pass in these tests must be valid.

**`tests/test_declarations.py`**:

- add a valid declaration to `test_a_valid_declaration_of_each_kind` (one per params form);
- add invalid ones to the `test_invalid_declarations_are_rejected` parametrize list: an unknown
  param, each missing required param, each out-of-range or ill-typed value.

```bash
uv run pytest tests/test_checks.py tests/test_declarations.py -q -k "<kind>"
uv run pytest tests/test_declarations.py -q
```

(`docker compose run --rm app pytest ...` also works; `uv run` needs
`docker compose up -d db` for Postgres on port 55432.) The first command selects only the check tests (the declaration tests' names do
not contain the kind), so run both. The new check tests must fail now with
`unknown check kind '<kind>'`, and `test_a_valid_declaration_of_each_kind` with a
`ValidationError`. The new *invalid*-declaration cases already pass (an unknown kind is
rejected anyway); that is expected, and they start meaning something once the kind exists.

## 3. Declaration: `app/declarations.py`

```python
class <Kind>Params(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Typed fields, with Field(gt=0, min_length=1, ...) for simple constraints and a
    # model_validator for rules across fields. Validate anything a declaration could get
    # wrong (e.g. compile a regex in a field_validator and raise ValueError on re.error).
```

Add `"<kind>"` to the `CheckKind` `Literal` **and** `"<kind>": <Kind>Params` to `PARAMS`.
A kind with no params uses an empty model, like `CompletenessParams`.

## 4. Evaluation: `jobs/run_checks.py`

Write one function next to the other kinds and register it in `EVALUATORS`.

- **Per-record rule**: a rule `def <kind>(check: Check, value: object, run_date: date) -> str`
  registered as `"<kind>": each_record(<kind>)`. `value` is `None` when the field is absent.
- **Dataset-level rule**: a full evaluator
  `def <kind>(check: Check, records: list[Record], run_date: date) -> list[str]`, registered
  directly as `"<kind>": <kind>`. Read values with `record.data.get(check.field)`, compute what
  you need over all records first (e.g. a `collections.Counter`), then return exactly one
  detail per record, in the order given. How missing values take part is a step-0 decision for
  your rule. For example, `uniqueness` fails them as missing and leaves them out of the counts,
  so two missing values are not duplicates of each other; another rule may need otherwise.
  Make values hashable before counting: `json.dumps(value, sort_keys=True)` works for every
  JSON value and already keeps `1`, `1.0`, `"1"` and `true` apart; or fail lists and dicts as
  the wrong type, per your decision.

Rules for both:

- Params are stored **as declared** (raw dict): model defaults, coercions (`"5"` to `5`, an
  int to a float) and normalisation done by validators are not applied in storage. If the
  model has any of these, the evaluator must read params through the model,
  `params = <Kind>Params.model_validate(check.params)`, and use `params.<name>` everywhere, so
  the job evaluates exactly what validation accepted. Reading `check.params[...]` directly is
  only safe when the model neither defaults nor changes any value.
- Guard types with `isinstance` before comparing or parsing; exclude `bool` from numeric rules.
  One bad record must never raise.
- Pass: `""`. Fail: short, naming the field and the value, in the style of the others:
  `f"{check.field}={value!r} is not one of {allowed}"`, `f"{check.field} is missing"`.
- Update the module docstring or comments only if they list the kinds.

Run the step-2 tests again: they must pass now.

## 5. Fixture: `fixtures/datasets.json`

Add one check of the new kind to a dataset whose records give **at least one pass and one
fail**. Verify against the data rather than guessing (prints each record's key and value):

```bash
python3 -I -c "import json,sys; [print(r['key'], repr(r['data'].get(sys.argv[2]))) for r in json.load(open(sys.argv[1]))]" fixtures/records/<dataset>.json <field>
```

Prefer an existing dataset and existing records. Only if none gives both a pass and a fail,
add or change one record in the most natural dataset, and say so. Keep the file's JSON style
(2-space indent). `test_every_fixture_check_is_valid` validates the declaration.

## 6. Docs: `docs/checks.md`

Append a section in the same shape as the others: the rule in one sentence, then the
decisions from step 0 that a person declaring the check needs to know, then params, then one
example declaration (the fixture's, if it reads well):

~~~markdown
## <kind>

A record passes when <rule>. <Decisions: missing/null, types, case, ... in one or two sentences.>

Params: `<name>` (<type and constraint>), ... (or "Params: none.")

```json
{"name": "...", "kind": "<kind>", "field": "...", "params": {...}}
```
~~~

## 7. Verify

```bash
make test
```

`make test` runs the whole suite in Docker (`docker compose run --rm app pytest`; run
`make up` first if the image is not built). If Docker for the app is not available, use
`docker compose up -d db && uv run pytest`. Every test must pass, not only the new ones; if an
unrelated test fails, report it by name rather than changing it.

Then run the job on the fixtures. **The seed drops and recreates every table in the database
`DATABASE_URL` points at** (the compose stack's `checks` database by default), deleting all
runs and results there. If that database holds anything that must be kept, or the user asked
for an isolated database, point `DATABASE_URL` at another database first.

```bash
make seed && make run-job        # the job must log "finished: succeeded"
# or: uv run python -m scripts.seed && uv run python -m jobs.run_checks --date 2026-11-03
```

List the new check's failures in the latest run (same `DATABASE_URL` as the job):

```bash
uv run python -c "import sys; from sqlalchemy import select, func; from app.db import SessionLocal; from app.models import Check, Record, Result; s = SessionLocal(); run = s.scalar(select(func.max(Result.run_id))); [print(*row) for row in s.execute(select(Record.key, Result.detail).join(Result, Result.record_id == Record.id).join(Check, Check.id == Result.check_id).where(Result.run_id == run, Check.kind == sys.argv[1], Result.passed.is_(False)).order_by(Record.key))]" <kind>
```

The failing records should be exactly the ones you expected in step 5.

## Done when

- [ ] `<Kind>Params` with `extra="forbid"`; the kind in both `CheckKind` and `PARAMS`
- [ ] evaluator in `EVALUATORS`; one detail per record; no database queries; never raises
- [ ] tests: pass, fail, missing/null, one per decision, detail text; valid and invalid declarations
- [ ] tests were seen failing before the implementation
- [ ] fixture check on a dataset with verified passing and failing records
- [ ] `docs/checks.md` section: rule, decisions, params, example
- [ ] `make test` (or `uv run pytest`) fully green; the job succeeds on the fixtures
- [ ] no unrelated changes; problems found elsewhere are reported, not fixed

Finish with a short summary with these parts, in this order:

1. **Files changed**, one line each.
2. **Decisions** from step 0, including any name you chose (param names, for example).
3. **Commands run** (tests, seed, job, failure listing) and the result of each.
4. **Unresolved**: failing tests by name, anything left undone, and problems found elsewhere.
   Write "none" if there are none.
5. **Skill gaps**: each place where this skill was wrong, unclear or missing something, and
   what you did instead. Write "none" if there are none.
