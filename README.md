# Checks service

A small data-quality service. It holds several datasets, the records in each, and the
lineage between them (which dataset is built from which). Each dataset has an owner and a
set of declared checks. Once a day a job runs every check over its dataset's records,
stores the results and tells owners about failures.

The task is in the assessment instructions. This README is about running the code.

## You need

Docker (with Compose) and git. Nothing else: no accounts or keys.

## Start

```bash
make up        # builds the image, starts Postgres, Redis, the API and the worker
make seed      # loads the fixtures (replaces what is in the database)
make run-job   # runs the checks for 2026-11-03; another day: make run-job DATE=2026-11-04
make test      # runs the tests
```

The API is at http://localhost:8000 (interactive docs at http://localhost:8000/docs).
`make logs` follows the API and worker logs; `make down` stops everything and deletes the data.

The first `make up` downloads images and dependencies, which takes a few minutes. After that,
code changes apply without rebuilding: the source is mounted into the containers.

## Without make

Each `make` target is one Docker Compose command, for machines without `make` (Windows outside WSL):

| make | docker compose |
|-|-|
| `make up` | `docker compose up -d --build` |
| `make seed` | `docker compose run --rm app python -m scripts.seed` |
| `make run-job DATE=2026-11-03` | `docker compose run --rm app python -m jobs.run_checks --date 2026-11-03` |
| `make test` | `docker compose run --rm app pytest` |
| `make logs` | `docker compose logs -f app worker` |
| `make down` | `docker compose down -v` |

## Without Docker for the app

Keep `docker compose up -d db` for Postgres (published on port 55432), then:

```bash
uv sync
uv run python -m scripts.seed
uv run python -m jobs.run_checks --date 2026-11-03
uv run pytest
```

The defaults in `app/config.py` point at that Postgres; override with `DATABASE_URL` and
`TEST_DATABASE_URL`.

## Where things are

See `CONTRIBUTING.md` for the layout and conventions, and `docs/checks.md` for what each check
kind means.
