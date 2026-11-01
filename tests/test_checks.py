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


def test_uniqueness_passes_distinct_values_and_fails_every_duplicate(session, notifications):
    result = outcomes(session, "uniqueness", "id", {"a": "x", "b": "y", "c": "x"})
    assert result == {"a": False, "b": True, "c": False}


def test_uniqueness_fails_missing_or_null_without_counting_them_as_duplicates(session, notifications):
    # Missing and null fail as missing; two of them do not make each other duplicates, and
    # they do not make the one real value a duplicate either.
    result = outcomes(session, "uniqueness", "id", {"absent": ..., "null": None, "other_null": None, "a": "x"})
    assert result == {"absent": False, "null": False, "other_null": False, "a": True}


def test_uniqueness_compares_values_with_their_type(session, notifications):
    # 1, 1.0, "1" and true are four different JSON values.
    result = outcomes(session, "uniqueness", "id", {"int": 1, "float": 1.0, "str": "1", "bool": True})
    assert result == {"int": True, "float": True, "str": True, "bool": True}


def test_uniqueness_is_case_and_whitespace_sensitive(session, notifications):
    result = outcomes(session, "uniqueness", "id", {"lower": "abc", "upper": "ABC", "padded": " abc"})
    assert result == {"lower": True, "upper": True, "padded": True}


def test_uniqueness_compares_lists_and_objects_by_value(session, notifications):
    values = {"list": [1, 2], "same_list": [1, 2], "other_list": [2, 1],
              "obj": {"a": 1, "b": 2}, "same_obj": {"b": 2, "a": 1}}
    result = outcomes(session, "uniqueness", "id", values)
    assert result == {"list": False, "same_list": False, "other_list": True, "obj": False, "same_obj": False}


def test_uniqueness_treats_blank_strings_as_values(session, notifications):
    # Blank is completeness' concern: one "" is unique, two collide.
    result = outcomes(session, "uniqueness", "id", {"a": "", "b": "", "c": " "})
    assert result == {"a": False, "b": False, "c": True}


def test_uniqueness_detail_names_the_field_and_value(session, notifications):
    outcomes(session, "uniqueness", "id", {"bad": "x", "bad2": "x", "ok": "y", "none": ...})
    details = dict(session.execute(
        select(Record.key, Result.detail).join(Result, Result.record_id == Record.id)
    ).all())
    assert details == {"bad": "id='x' is shared by 2 records", "bad2": "id='x' is shared by 2 records",
                       "ok": "", "none": "id is missing"}
