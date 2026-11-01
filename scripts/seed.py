"""Loads the fixtures into the database, replacing whatever is there.

    python -m scripts.seed

fixtures/datasets.json declares the datasets, their owners, what each is built from and
their checks; fixtures/records/<dataset>.json holds each dataset's records.
"""

import json
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import Base, engine
from app.declarations import CheckDeclaration
from app.models import Check, Dataset, Lineage, Record

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load(session: Session, fixtures: Path = FIXTURES) -> None:
    spec = json.loads((fixtures / "datasets.json").read_text())

    datasets: dict[str, Dataset] = {}
    for entry in spec["datasets"]:
        dataset = Dataset(name=entry["name"], owner=entry["owner"])
        session.add(dataset)
        datasets[entry["name"]] = dataset
    session.flush()

    for entry in spec["datasets"]:
        dataset = datasets[entry["name"]]
        for upstream in entry.get("built_from", []):
            session.add(Lineage(upstream_id=datasets[upstream].id, downstream_id=dataset.id))
        for raw in entry.get("checks", []):
            declared = CheckDeclaration.model_validate(raw)
            session.add(
                Check(dataset_id=dataset.id, name=declared.name, kind=declared.kind,
                      field=declared.field, params=declared.params)
            )
        records_file = fixtures / "records" / f"{entry['name']}.json"
        for row in json.loads(records_file.read_text()):
            session.add(Record(dataset_id=dataset.id, key=row["key"], data=row["data"]))

    session.commit()


def reset(bind: Engine = engine) -> None:
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind)
    Base.metadata.create_all(bind)


def main() -> None:
    reset()
    with Session(engine) as session:
        load(session)
    print("seeded")


if __name__ == "__main__":
    main()
