# Contributing

## Running things

Everything runs in Docker; see the README for the commands. `make test` must pass before a
change is done.

## Layout

| Path | What it holds |
|-|-|
| `app/models.py` | The tables: datasets, lineage, records, checks, runs, results |
| `app/declarations.py` | Which check kinds exist and the parameters each takes |
| `jobs/run_checks.py` | The daily job, including how each check kind is evaluated |
| `app/main.py` | The HTTP API |
| `app/notify.py` | Notifications to dataset owners (logged only) |
| `fixtures/` | Synthetic datasets, lineage, checks (`datasets.json`) and records (`records/`) |
| `docs/checks.md` | What each check kind means, for the people who declare checks |
| `tests/` | pytest; `tests/conftest.py` has the database fixtures and `add_dataset` |

## Conventions

- Python 3.13, type hints on every function, SQLAlchemy 2.0 style (`select(...)`, `Mapped`).
- Tests use the `session` fixture and `add_dataset` from `tests/conftest.py`, and the run date
  `2026-11-03`. Each test builds the little data it needs; the fixtures in `fixtures/` are for
  running the job by hand.
- Results carry a short `detail` saying why a record failed, naming the field and the value.
- Keep commits small, with a message that says what changed and why.

## Adding a check kind

A new kind touches five places, in this order:

1. **Declaration.** In `app/declarations.py`, add a params model (`extra="forbid"`, validating
   anything a declaration could get wrong), add the kind to `CheckKind` and to `PARAMS`.
2. **Evaluation.** In `jobs/run_checks.py`, evaluate the kind for each record of the dataset,
   storing a result with a `detail` for each failure.
3. **Fixtures.** Declare one check of the new kind in `fixtures/datasets.json`, on a dataset
   whose records include at least one pass and one failure.
4. **Tests.** In `tests/test_checks.py`, at least one passing and one failing case, plus any edge
   the definition names; in `tests/test_declarations.py`, a valid and an invalid declaration.
5. **Docs.** A section in `docs/checks.md` in the same shape as the others: the rule in one
   sentence, the params, one example declaration.

Then run `make test`.
