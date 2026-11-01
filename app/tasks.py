"""Celery wiring: runs the checks job every morning."""

from datetime import date

from celery import Celery
from celery.schedules import crontab

from app.config import settings
from app.db import SessionLocal, init_db

celery_app = Celery("checks", broker=settings.redis_url)
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "daily-checks": {"task": "app.tasks.run_daily_checks", "schedule": crontab(hour=6, minute=0)},
}


@celery_app.task
def run_daily_checks(run_date: str | None = None) -> int:
    from jobs.run_checks import run_checks

    init_db()
    with SessionLocal() as session:
        run = run_checks(session, date.fromisoformat(run_date) if run_date else date.today())
    return run.id
