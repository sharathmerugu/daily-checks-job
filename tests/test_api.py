from datetime import date

from jobs.run_checks import run_checks
from tests.conftest import add_dataset


def test_datasets_show_what_they_are_built_from(session, client):
    raw = add_dataset(session, "raw_orders")
    add_dataset(session, "stg_orders", owner="ben@example.com", built_from=[raw])
    body = client.get("/datasets").json()
    assert [(d["name"], d["built_from"]) for d in body] == [("raw_orders", []), ("stg_orders", ["raw_orders"])]


def test_results_of_a_run(session, client, notifications):
    add_dataset(session, "customers", checks=[{"name": "email present", "kind": "completeness", "field": "email"}],
                records={"a": {"email": "a@example.com"}, "b": {}})
    run = run_checks(session, date(2026, 11, 3))

    everything = client.get(f"/runs/{run.id}/results").json()
    failed = client.get(f"/runs/{run.id}/results", params={"failed_only": True}).json()

    assert len(everything) == 2
    assert [(r["record_key"], r["passed"]) for r in failed] == [("b", False)]


def test_unknown_run_is_not_found(client):
    assert client.get("/runs/999999/results").status_code == 404
