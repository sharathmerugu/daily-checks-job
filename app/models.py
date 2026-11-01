from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    owner: Mapped[str] = mapped_column(String(200))


class Lineage(Base):
    """One edge of the lineage graph: `downstream` is built from `upstream`."""

    __tablename__ = "lineage"

    upstream_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), primary_key=True)
    downstream_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), primary_key=True)


class Record(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSONB)


class Check(Base):
    """A declared check. `kind` and `params` are validated by app.declarations."""

    __tablename__ = "checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30))
    field: Mapped[str] = mapped_column(String(100))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("checks.id"))
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id"))
    passed: Mapped[bool]
    detail: Mapped[str] = mapped_column(Text, default="")
