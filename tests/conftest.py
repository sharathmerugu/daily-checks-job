from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.config import settings
from app.db import Base, get_session
from app.main import app


def _ensure_database(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("select 1 from pg_database where datname = :n"), {"n": target.database})
        if not exists:
            conn.execute(text(f'create database "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    _ensure_database(settings.test_database_url)
    eng = create_engine(settings.test_database_url)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        yield s


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@dataclass
class Notifications:
    failures: list[tuple] = field(default_factory=list)
    digests: list[tuple] = field(default_factory=list)


@pytest.fixture
def notifications(monkeypatch: pytest.MonkeyPatch) -> Notifications:
    """Captures what the job sends instead of logging it."""
    sent = Notifications()
    monkeypatch.setattr("app.notify.Notifier.send_failure",
                        lambda self, owner, failure: sent.failures.append((owner, failure)))
    monkeypatch.setattr("app.notify.Notifier.send_digest",
                        lambda self, owner, run_date, failures: sent.digests.append((owner, run_date, failures)))
    return sent


def add_dataset(
    session: Session,
    name: str,
    *,
    owner: str = "owner@example.com",
    checks: list[dict] = (),
    records: dict[str, dict] | None = None,
    built_from: list[models.Dataset] = (),
) -> models.Dataset:
    """Adds a dataset with its checks, records ({key: data}) and upstream datasets."""
    dataset = models.Dataset(name=name, owner=owner)
    session.add(dataset)
    session.flush()
    for upstream in built_from:
        session.add(models.Lineage(upstream_id=upstream.id, downstream_id=dataset.id))
    for check in checks:
        session.add(models.Check(dataset_id=dataset.id, name=check["name"], kind=check["kind"],
                                 field=check["field"], params=check.get("params", {})))
    for key, data in (records or {}).items():
        session.add(models.Record(dataset_id=dataset.id, key=key, data=data))
    session.commit()
    return dataset
