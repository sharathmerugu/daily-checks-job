from datetime import date

from app import models
from jobs.run_checks import run_checks
from tests.conftest import add_dataset
from tests.test_job import count_statements

RUN_DATE = date(2026, 11, 3)

EMAIL_PRESENT = [{"name": "email present", "kind": "completeness", "field": "email"}]


def add_failing(session, name: str, **kwargs) -> models.Dataset:
    """A dataset whose one record fails its one check."""
    return add_dataset(session, name, checks=EMAIL_PRESENT, records={"x": {}}, **kwargs)


def impact(client, run_id: int, dataset_id: int):
    return client.get(f"/runs/{run_id}/datasets/{dataset_id}/impact")


def impacted(response) -> list[tuple[str, int]]:
    assert response.status_code == 200, response.text
    return [(d["name"], d["hops"]) for d in response.json()["impacted"]]


def test_impact_lists_direct_and_indirect_downstream_datasets(session, client, notifications):
    raw = add_failing(session, "raw")
    stg = add_dataset(session, "stg", built_from=[raw])
    mart = add_dataset(session, "mart", built_from=[stg])
    add_dataset(session, "dashboard", built_from=[mart])
    add_dataset(session, "unrelated")
    run = run_checks(session, RUN_DATE)

    response = impact(client, run.id, raw.id)

    assert impacted(response) == [("stg", 1), ("mart", 2), ("dashboard", 3)]
    body = response.json()
    assert (body["run_id"], body["dataset_id"]) == (run.id, raw.id)
    assert body["impacted"][0] == {"dataset_id": stg.id, "name": "stg", "owner": "owner@example.com", "hops": 1}


def test_impact_reports_each_dataset_once_with_the_fewest_hops(session, client, notifications):
    # raw -> left -> right -> joined, and also raw -> right: right is 1 hop away, joined 2.
    raw = add_failing(session, "raw")
    left = add_dataset(session, "left", built_from=[raw])
    right = add_dataset(session, "right", built_from=[raw, left])
    add_dataset(session, "joined", built_from=[left, right])
    run = run_checks(session, RUN_DATE)

    assert impacted(impact(client, run.id, raw.id)) == [("left", 1), ("right", 1), ("joined", 2)]


def test_impact_survives_a_cycle_and_leaves_out_the_failed_dataset(session, client, notifications):
    raw = add_failing(session, "raw")
    scores = add_dataset(session, "scores", built_from=[raw])
    segments = add_dataset(session, "segments", built_from=[scores])
    session.add(models.Lineage(upstream_id=segments.id, downstream_id=scores.id))
    session.add(models.Lineage(upstream_id=segments.id, downstream_id=raw.id))
    session.commit()
    run = run_checks(session, RUN_DATE)

    assert impacted(impact(client, run.id, raw.id)) == [("scores", 1), ("segments", 2)]


def test_impact_of_a_failed_dataset_with_nothing_downstream_is_empty(session, client, notifications):
    raw = add_failing(session, "raw")
    upstream = add_dataset(session, "upstream")
    session.add(models.Lineage(upstream_id=upstream.id, downstream_id=raw.id))
    session.commit()
    run = run_checks(session, RUN_DATE)

    assert impacted(impact(client, run.id, raw.id)) == []


def test_impact_of_an_unknown_run_or_dataset_is_not_found(session, client, notifications):
    raw = add_failing(session, "raw")
    run = run_checks(session, RUN_DATE)

    unknown_run = impact(client, run.id + 1, raw.id)
    unknown_dataset = impact(client, run.id, raw.id + 1000)

    assert (unknown_run.status_code, unknown_run.json()["detail"]) == (404, f"run {run.id + 1} not found")
    assert (unknown_dataset.status_code, unknown_dataset.json()["detail"]) == (
        404, f"dataset {raw.id + 1000} not found")


def test_impact_of_a_dataset_that_did_not_fail_in_the_run_is_a_conflict(session, client, notifications):
    clean = add_dataset(session, "clean", checks=EMAIL_PRESENT, records={"x": {"email": "x@example.com"}})
    add_dataset(session, "downstream", built_from=[clean])
    run = run_checks(session, RUN_DATE)

    response = impact(client, run.id, clean.id)

    assert response.status_code == 409
    assert "no failures" in response.json()["detail"]


def test_impact_round_trips_do_not_grow_with_the_graph(session, client, notifications, engine):
    raw = add_failing(session, "raw")
    add_dataset(session, "stg", built_from=[raw])
    run = run_checks(session, RUN_DATE)
    with count_statements(engine) as small:
        impact(client, run.id, raw.id)

    previous = add_dataset(session, "deep0", built_from=[raw])
    for depth in range(1, 7):
        previous = add_dataset(session, f"deep{depth}", built_from=[previous, raw])
    with count_statements(engine) as big:
        assert len(impacted(impact(client, run.id, raw.id))) == 8

    assert len(big) == len(small)
