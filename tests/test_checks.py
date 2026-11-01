"""Each check kind, as docs/checks.md describes it."""

from datetime import date

from sqlalchemy import select

from app.models import Record, Result
from jobs.run_checks import run_checks
from tests.conftest import add_dataset

RUN_DATE = date(2026, 11, 3)


def outcomes(session, kind: str, field: str, values: dict[str, object], params: dict | None = None) -> dict[str, bool]:
    """Runs one check over records whose `field` takes each value; returns {key: passed}.

    A value of ... leaves the field out of the record.
    """
    records = {key: ({} if value is ... else {field: value}) for key, value in values.items()}
    add_dataset(session, "d", checks=[{"name": "c", "kind": kind, "field": field, "params": params or {}}],
                records=records)
    run = run_checks(session, RUN_DATE)
    rows = session.execute(
        select(Record.key, Result.passed).join(Result, Result.record_id == Record.id).where(Result.run_id == run.id)
    )
    return dict(rows.all())


def test_completeness_passes_when_value_present(session, notifications):
    assert outcomes(session, "completeness", "email", {"a": "a@example.com"}) == {"a": True}


def test_completeness_fails_when_field_missing_or_null(session, notifications):
    assert outcomes(session, "completeness", "email", {"a": ..., "b": None}) == {"a": False, "b": False}


def test_completeness_fails_when_value_blank(session, notifications):
    assert outcomes(session, "completeness", "email", {"a": "", "b": "   "}) == {"a": False, "b": False}


def test_accuracy_allowed_values(session, notifications):
    result = outcomes(session, "accuracy", "country", {"a": "GB", "b": "XX"}, {"allowed": ["GB", "US"]})
    assert result == {"a": True, "b": False}


def test_accuracy_range_is_inclusive(session, notifications):
    values = {"low": 0, "high": 10, "under": -1, "over": 11}
    result = outcomes(session, "accuracy", "amount", values, {"min": 0, "max": 10})
    assert result == {"low": True, "high": True, "under": False, "over": False}


def test_timeliness_fails_when_too_old(session, notifications):
    # 48 hours before 00:00 UTC on the run date, with a 24-hour limit
    result = outcomes(session, "timeliness", "updated_at", {"a": "2026-11-01T00:00:00Z"}, {"max_age_hours": 24})
    assert result == {"a": False}


def test_timeliness_passes_when_recent(session, notifications):
    # 12 hours before 00:00 UTC on the run date, with a 24-hour limit
    result = outcomes(session, "timeliness", "updated_at", {"a": "2026-11-02T12:00:00Z"}, {"max_age_hours": 24})
    assert result == {"a": True}


# Decisions on cases the rules leave open (see NOTES.md).


def test_completeness_treats_any_whitespace_as_blank(session, notifications):
    assert outcomes(session, "completeness", "email", {"tab": "\t", "newline": "\n "}) == {
        "tab": False, "newline": False,
    }


def test_completeness_passes_falsy_non_string_values(session, notifications):
    # 0, False and empty containers are present values, not blanks.
    assert outcomes(session, "completeness", "n", {"zero": 0, "false": False, "empty_list": []}) == {
        "zero": True, "false": True, "empty_list": True,
    }


def test_timeliness_passes_at_exactly_max_age(session, notifications):
    # "no more than" 24 hours: exactly 24 hours before 00:00 UTC passes, a second more fails.
    result = outcomes(session, "timeliness", "updated_at",
                      {"edge": "2026-11-02T00:00:00Z", "over": "2026-11-01T23:59:59Z"}, {"max_age_hours": 24})
    assert result == {"edge": True, "over": False}


def test_timeliness_reads_timestamps_without_offset_as_utc(session, notifications):
    result = outcomes(session, "timeliness", "updated_at",
                      {"naive": "2026-11-02T00:00:00", "offset": "2026-11-02T01:00:00+01:00"}, {"max_age_hours": 24})
    assert result == {"naive": True, "offset": True}


def test_timeliness_passes_timestamps_after_the_reference(session, notifications):
    # Later than 00:00 UTC on the run date: the age is negative, so never too old.
    result = outcomes(session, "timeliness", "updated_at", {"a": "2026-11-03T08:00:00Z"}, {"max_age_hours": 24})
    assert result == {"a": True}
