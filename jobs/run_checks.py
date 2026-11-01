"""The daily checks job.

For one run date it evaluates every dataset's declared checks over the dataset's
records, stores one result per record and check, and sends each owner one digest listing
every failure in the datasets they own.

    python -m jobs.run_checks --date 2026-11-03
"""

import argparse
import json
import logging
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models import Check, Dataset, Record, Result, Run
from app.notify import Failure, Notifier

log = logging.getLogger("jobs.run_checks")

# An evaluator gets a check, every record of the check's dataset (in id order) and the run
# date, and returns one detail per record: "" when the record passed, otherwise why it failed.
Evaluator = Callable[[Check, list[Record], date], list[str]]
# A rule judges one record from the value of the check's field (None when the field is absent).
Rule = Callable[[Check, object, date], str]


def each_record(rule: Rule) -> Evaluator:
    """Turns a rule about one record's value into an evaluator over a dataset's records."""

    def evaluate(check: Check, records: list[Record], run_date: date) -> list[str]:
        return [rule(check, record.data.get(check.field), run_date) for record in records]

    return evaluate


def completeness(check: Check, value: object, run_date: date) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return f"{check.field} is missing"
    return ""


def accuracy(check: Check, value: object, run_date: date) -> str:
    if value is None:
        return f"{check.field} is missing"
    allowed = check.params.get("allowed")
    if allowed is not None:
        return "" if value in allowed else f"{check.field}={value!r} is not one of {allowed}"
    low, high = check.params.get("min"), check.params.get("max")
    if (low is not None and value < low) or (high is not None and value > high):
        return f"{check.field}={value!r} is outside [{low}, {high}]"
    return ""


def timeliness(check: Check, value: object, run_date: date) -> str:
    if value is None:
        return f"{check.field} is missing"
    max_age = timedelta(hours=check.params["max_age_hours"])
    reference = datetime.combine(run_date, time.min, tzinfo=UTC)
    updated = datetime.fromisoformat(value)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    age = reference - updated
    if age > max_age:
        return f"{check.field} is {age} old, more than {max_age}"
    return ""


def uniqueness(check: Check, records: list[Record], run_date: date) -> list[str]:
    # Values are compared as JSON values: 1, 1.0, "1" and true all differ, strings are
    # compared exactly, and lists and objects by content (object key order does not matter).
    def key(value: object) -> str:
        return json.dumps(value, sort_keys=True)

    values = [record.data.get(check.field) for record in records]
    counts = Counter(key(value) for value in values if value is not None)
    details = []
    for value in values:
        if value is None:
            details.append(f"{check.field} is missing")
        elif (count := counts[key(value)]) > 1:
            details.append(f"{check.field}={value!r} is shared by {count} records")
        else:
            details.append("")
    return details


EVALUATORS: dict[str, Evaluator] = {
    "completeness": each_record(completeness),
    "accuracy": each_record(accuracy),
    "timeliness": each_record(timeliness),
    "uniqueness": uniqueness,
}


def run_checks(session: Session, run_date: date) -> Run:
    run = Run(run_date=run_date, status="running", started_at=datetime.now(UTC))
    session.add(run)
    session.commit()

    # Three queries load everything the run needs, however many datasets, checks and records.
    datasets = session.scalars(select(Dataset).order_by(Dataset.id)).all()
    checks_by_dataset: dict[int, list[Check]] = defaultdict(list)
    for check in session.scalars(select(Check).order_by(Check.dataset_id, Check.id)):
        checks_by_dataset[check.dataset_id].append(check)
    records_by_dataset: dict[int, list[Record]] = defaultdict(list)
    for record in session.scalars(select(Record).order_by(Record.dataset_id, Record.id)):
        records_by_dataset[record.dataset_id].append(record)

    failures_by_owner: dict[str, list[Failure]] = defaultdict(list)
    for dataset in datasets:
        records = records_by_dataset[dataset.id]
        for check in checks_by_dataset[dataset.id]:
            evaluate = EVALUATORS.get(check.kind)
            if evaluate is None:
                raise ValueError(f"unknown check kind {check.kind!r} on check {check.id}")
            for record, detail in zip(records, evaluate(check, records, run_date), strict=True):
                session.add(Result(run_id=run.id, check_id=check.id, record_id=record.id,
                                   passed=not detail, detail=detail))
                if detail:
                    failures_by_owner[dataset.owner].append(
                        Failure(dataset.name, check.name, record.key, detail))

    # The results and the finished run are written together, in batched inserts and one commit.
    run.status = "succeeded"
    run.finished_at = datetime.now(UTC)
    session.commit()

    # One digest per owner with failures, sent only once the results are committed.
    notifier = Notifier()
    for owner, failures in failures_by_owner.items():
        notifier.send_digest(owner, run_date, failures)
    return run


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run every dataset's checks for one day.")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    init_db()
    with SessionLocal() as session:
        run = run_checks(session, args.date)
    log.info("run %s for %s finished: %s", run.id, run.run_date, run.status)


if __name__ == "__main__":
    main()
