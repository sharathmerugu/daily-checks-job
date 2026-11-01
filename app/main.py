from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session, init_db
from app.models import Check, Dataset, Lineage, Record, Result, Run


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Checks service", lifespan=lifespan)


class DatasetOut(BaseModel):
    id: int
    name: str
    owner: str
    built_from: list[str]


class RunOut(BaseModel):
    id: int
    run_date: date
    status: str
    started_at: datetime
    finished_at: datetime | None


class ResultOut(BaseModel):
    dataset: str
    check: str
    record_key: str
    passed: bool
    detail: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/datasets")
def list_datasets(session: Session = Depends(get_session)) -> list[DatasetOut]:
    datasets = session.scalars(select(Dataset).order_by(Dataset.id)).all()
    names = {d.id: d.name for d in datasets}
    upstream: dict[int, list[str]] = {d.id: [] for d in datasets}
    for edge in session.scalars(select(Lineage)):
        upstream[edge.downstream_id].append(names[edge.upstream_id])
    return [
        DatasetOut(id=d.id, name=d.name, owner=d.owner, built_from=sorted(upstream[d.id]))
        for d in datasets
    ]


@app.get("/runs")
def list_runs(session: Session = Depends(get_session)) -> list[RunOut]:
    runs = session.scalars(select(Run).order_by(Run.id.desc())).all()
    return [RunOut.model_validate(r, from_attributes=True) for r in runs]


@app.get("/runs/{run_id}/results")
def list_results(
    run_id: int, failed_only: bool = False, session: Session = Depends(get_session)
) -> list[ResultOut]:
    if session.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    query = (
        select(Result, Check, Record, Dataset)
        .join(Check, Result.check_id == Check.id)
        .join(Record, Result.record_id == Record.id)
        .join(Dataset, Check.dataset_id == Dataset.id)
        .where(Result.run_id == run_id)
        .order_by(Result.id)
    )
    if failed_only:
        query = query.where(Result.passed.is_(False))
    return [
        ResultOut(dataset=d.name, check=c.name, record_key=rec.key, passed=r.passed, detail=r.detail)
        for r, c, rec, d in session.execute(query)
    ]
