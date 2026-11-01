DATE ?= 2026-11-03

.PHONY: up seed run-job test down logs

up:
	docker compose up -d --build

seed:
	docker compose run --rm app python -m scripts.seed

run-job:
	docker compose run --rm app python -m jobs.run_checks --date $(DATE)

test:
	docker compose run --rm app pytest

logs:
	docker compose logs -f app worker

down:
	docker compose down -v
