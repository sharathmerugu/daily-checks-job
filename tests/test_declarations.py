import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.declarations import CheckDeclaration


def declare(**fields) -> CheckDeclaration:
    return CheckDeclaration.model_validate({"name": "c", "field": "f", **fields})


def test_a_valid_declaration_of_each_kind():
    declare(kind="completeness")
    declare(kind="accuracy", params={"allowed": ["a"]})
    declare(kind="accuracy", params={"min": 0})
    declare(kind="timeliness", params={"max_age_hours": 24})
    declare(kind="uniqueness")


@pytest.mark.parametrize("fields", [
    {"kind": "freshness"},
    {"kind": "completeness", "params": {"min": 1}},
    {"kind": "accuracy"},
    {"kind": "accuracy", "params": {"allowed": ["a"], "max": 3}},
    {"kind": "timeliness", "params": {"max_age_hours": 0}},
    {"kind": "uniqueness", "params": {"case_sensitive": False}},
])
def test_invalid_declarations_are_rejected(fields):
    with pytest.raises(ValidationError):
        declare(**fields)


def test_every_fixture_check_is_valid():
    spec = json.loads((Path(__file__).parent.parent / "fixtures" / "datasets.json").read_text())
    for dataset in spec["datasets"]:
        for check in dataset["checks"]:
            CheckDeclaration.model_validate(check)
