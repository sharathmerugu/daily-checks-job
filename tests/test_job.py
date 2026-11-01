from datetime import date

from sqlalchemy import func, select

from app.models import Result, Run
from jobs.run_checks import run_checks
from tests.conftest import add_dataset

RUN_DATE = date(2026, 11, 3)

CHECKS = [
    {"name": "email present", "kind": "completeness", "field": "email"},
    {"name": "country known", "kind": "accuracy", "field": "country", "params": {"allowed": ["GB"]}},
]


def test_job_stores_one_result_per_record_and_check(session, notifications):
    add_dataset(session, "customers", checks=CHECKS, records={
        "a": {"email": "a@example.com", "country": "GB"},
        "b": {"email": "b@example.com", "country": "US"},
        "c": {"country": "GB"},
    })
    run = run_checks(session, RUN_DATE)
    assert session.scalar(select(func.count()).select_from(Result).where(Result.run_id == run.id)) == 6
    assert session.scalar(
        select(func.count()).select_from(Result).where(Result.run_id == run.id, Result.passed.is_(False))
    ) == 2


def test_job_records_the_run(session, notifications):
    add_dataset(session, "customers", checks=CHECKS, records={"a": {"email": "a@example.com", "country": "GB"}})
    run = run_checks(session, RUN_DATE)
    stored = session.get(Run, run.id)
    assert stored.run_date == RUN_DATE
    assert stored.status == "succeeded"
    assert stored.finished_at is not None


def test_job_tells_the_owner_about_each_failure(session, notifications):
    add_dataset(session, "customers", owner="ana@example.com", checks=CHECKS, records={
        "a": {"email": "a@example.com", "country": "US"},
        "b": {"country": "GB"},
    })
    run_checks(session, RUN_DATE)
    assert sorted((owner, f.record_key, f.check) for owner, f in notifications.failures) == [
        ("ana@example.com", "a", "country known"),
        ("ana@example.com", "b", "email present"),
    ]
