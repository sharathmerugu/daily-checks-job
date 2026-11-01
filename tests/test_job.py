from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

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


def test_job_sends_each_owner_one_digest_listing_every_failure(session, notifications):
    add_dataset(session, "customers", owner="ana@example.com", checks=CHECKS, records={
        "a": {"email": "a@example.com", "country": "US"},
        "b": {"country": "GB"},
    })
    run_checks(session, RUN_DATE)
    assert notifications.failures == []
    assert len(notifications.digests) == 1
    owner, run_date, failures = notifications.digests[0]
    assert (owner, run_date) == ("ana@example.com", RUN_DATE)
    assert sorted((f.dataset, f.record_key, f.check) for f in failures) == [
        ("customers", "a", "country known"),
        ("customers", "b", "email present"),
    ]


def test_job_digest_covers_every_dataset_an_owner_has(session, notifications):
    add_dataset(session, "customers", owner="ana@example.com", checks=CHECKS,
                records={"a": {"country": "GB"}})
    add_dataset(session, "prospects", owner="ana@example.com", checks=CHECKS,
                records={"p": {"email": "p@example.com", "country": "US"}})
    add_dataset(session, "suppliers", owner="bo@example.com", checks=CHECKS,
                records={"s": {"country": "GB"}})
    run_checks(session, RUN_DATE)
    sent = {owner: sorted((f.dataset, f.record_key) for f in failures)
            for owner, _, failures in notifications.digests}
    assert len(notifications.digests) == 2
    assert sent == {
        "ana@example.com": [("customers", "a"), ("prospects", "p")],
        "bo@example.com": [("suppliers", "s")],
    }


def test_job_sends_no_digest_to_an_owner_without_failures(session, notifications):
    add_dataset(session, "customers", owner="ana@example.com", checks=CHECKS,
                records={"a": {"email": "a@example.com", "country": "GB"}})
    add_dataset(session, "suppliers", owner="bo@example.com", checks=CHECKS,
                records={"s": {"country": "GB"}})
    run_checks(session, RUN_DATE)
    assert [owner for owner, _, _ in notifications.digests] == ["bo@example.com"]


@contextmanager
def count_statements(engine: Engine) -> Iterator[list[str]]:
    """Collects every SQL statement sent to the database inside the block."""
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def add_customers(session, name: str, size: int) -> None:
    add_dataset(session, name, checks=CHECKS, records={
        f"r{i}": ({"email": "x@example.com", "country": "GB"} if i % 2 else {"country": "US"})
        for i in range(size)
    })


def test_job_round_trips_do_not_grow_with_records_or_checks(session, notifications, engine):
    add_customers(session, "small", 2)
    with count_statements(engine) as small:
        run_checks(session, RUN_DATE)

    session.query(Result).delete()
    session.query(Run).delete()
    session.commit()
    for i in range(3):
        add_customers(session, f"big{i}", 20)
    with count_statements(engine) as big:
        run_checks(session, RUN_DATE)

    assert len(big) == len(small)
