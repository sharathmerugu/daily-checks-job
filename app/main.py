from collections import defaultdict, deque
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import date, datetime

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import exists, select
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


class ImpactedDatasetOut(BaseModel):
    dataset_id: int
    name: str
    owner: str
    hops: int


class ImpactOut(BaseModel):
    run_id: int
    dataset_id: int
    impacted: list[ImpactedDatasetOut]


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


def downstream_hops(edges: Iterable[tuple[int, int]], start: int) -> dict[int, int]:
    """Fewest hops from `start` to every dataset downstream of it, `start` itself left out.

    Breadth-first, so the first time a dataset is reached is along a shortest path; datasets
    already reached are not visited again, which also stops the walk going round a cycle.
    """
    children: dict[int, list[int]] = defaultdict(list)
    for upstream, downstream in edges:
        children[upstream].append(downstream)
    hops = {start: 0}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for child in children[current]:
            if child not in hops:
                hops[child] = hops[current] + 1
                queue.append(child)
    del hops[start]
    return hops


@app.get("/runs/{run_id}/datasets/{dataset_id}/impact")
def dataset_impact(run_id: int, dataset_id: int, session: Session = Depends(get_session)) -> ImpactOut:
    """Every dataset downstream of one that failed in a run, with the fewest hops to each."""
    if session.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    if session.get(Dataset, dataset_id) is None:
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id} not found")
    failed = session.scalar(select(exists().where(
        Result.run_id == run_id,
        Result.passed.is_(False),
        Result.check_id == Check.id,
        Check.dataset_id == dataset_id,
    )))
    if not failed:
        raise HTTPException(status_code=409, detail=f"dataset {dataset_id} had no failures in run {run_id}")

    edges = session.execute(select(Lineage.upstream_id, Lineage.downstream_id)).all()
    hops = downstream_hops(edges, dataset_id)
    datasets = session.scalars(select(Dataset).where(Dataset.id.in_(hops))).all() if hops else []
    impacted = sorted(
        (ImpactedDatasetOut(dataset_id=d.id, name=d.name, owner=d.owner, hops=hops[d.id]) for d in datasets),
        key=lambda d: (d.hops, d.name),
    )
    return ImpactOut(run_id=run_id, dataset_id=dataset_id, impacted=impacted)
