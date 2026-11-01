"""The daily checks job.

For one run date it evaluates every dataset's declared checks over the dataset's
records, stores one result per record and check, and tells the dataset's owner about
each failure.

    python -m jobs.run_checks --date 2026-11-03
"""

import argparse
import logging
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models import Check, Dataset, Record, Result, Run
from app.notify import Failure, Notifier

log = logging.getLogger("jobs.run_checks")


def run_checks(session: Session, run_date: date) -> Run:
    run = Run(run_date=run_date, status="running", started_at=datetime.now(UTC))
    session.add(run)
    session.commit()

    notifier = Notifier()

    datasets = session.scalars(select(Dataset).order_by(Dataset.id)).all()
    for dataset in datasets:
        checks = session.scalars(
            select(Check).where(Check.dataset_id == dataset.id).order_by(Check.id)
        ).all()
        for check in checks:
            records = session.scalars(
                select(Record).where(Record.dataset_id == dataset.id).order_by(Record.id)
            ).all()

            if check.kind == "completeness":
                for record in records:
                    value = record.data.get(check.field)
                    if value is None or value == "":
                        passed = False
                        detail = f"{check.field} is missing"
                    else:
                        passed = True
                        detail = ""
                    session.add(
                        Result(run_id=run.id, check_id=check.id, record_id=record.id,
                               passed=passed, detail=detail)
                    )
                    session.commit()
                    if not passed:
                        owner = session.scalar(select(Dataset.owner).where(Dataset.id == dataset.id))
                        notifier.send_failure(
                            owner, Failure(dataset.name, check.name, record.key, detail)
                        )

            elif check.kind == "accuracy":
                for record in records:
                    value = record.data.get(check.field)
                    if value is None:
                        passed = False
                        detail = f"{check.field} is missing"
                    elif check.params.get("allowed") is not None:
                        if value in check.params["allowed"]:
                            passed = True
                            detail = ""
                        else:
                            passed = False
                            detail = f"{check.field}={value!r} is not one of {check.params['allowed']}"
                    else:
                        low = check.params.get("min")
                        high = check.params.get("max")
                        if (low is not None and value < low) or (high is not None and value > high):
                            passed = False
                            detail = f"{check.field}={value!r} is outside [{low}, {high}]"
                        else:
                            passed = True
                            detail = ""
                    session.add(
                        Result(run_id=run.id, check_id=check.id, record_id=record.id,
                               passed=passed, detail=detail)
                    )
                    session.commit()
                    if not passed:
                        owner = session.scalar(select(Dataset.owner).where(Dataset.id == dataset.id))
                        notifier.send_failure(
                            owner, Failure(dataset.name, check.name, record.key, detail)
                        )

            elif check.kind == "timeliness":
                max_age = timedelta(hours=check.params["max_age_hours"])
                reference = datetime.combine(run_date, time.max, tzinfo=UTC)
                for record in records:
                    value = record.data.get(check.field)
                    if value is None:
                        passed = False
                        detail = f"{check.field} is missing"
                    else:
                        updated = datetime.fromisoformat(value)
                        if updated.tzinfo is None:
                            updated = updated.replace(tzinfo=UTC)
                        age = reference - updated
                        if age > max_age:
                            passed = False
                            detail = f"{check.field} is {age} old, more than {max_age}"
                        else:
                            passed = True
                            detail = ""
                    session.add(
                        Result(run_id=run.id, check_id=check.id, record_id=record.id,
                               passed=passed, detail=detail)
                    )
                    session.commit()
                    if not passed:
                        owner = session.scalar(select(Dataset.owner).where(Dataset.id == dataset.id))
                        notifier.send_failure(
                            owner, Failure(dataset.name, check.name, record.key, detail)
                        )

            else:
                raise ValueError(f"unknown check kind {check.kind!r} on check {check.id}")

    run.status = "succeeded"
    run.finished_at = datetime.now(UTC)
    session.commit()
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
