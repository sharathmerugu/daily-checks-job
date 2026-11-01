"""Check declarations: the kinds a check can have and the parameters each kind takes.

Every check stored in the `checks` table is validated against these models when it is
loaded (see scripts/seed.py). docs/checks.md describes what each kind means.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CompletenessParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccuracyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: list[str] | None = None
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def one_form(self) -> "AccuracyParams":
        has_range = self.min is not None or self.max is not None
        if self.allowed is None and not has_range:
            raise ValueError("accuracy needs `allowed`, or `min` and/or `max`")
        if self.allowed is not None and has_range:
            raise ValueError("accuracy takes `allowed` or `min`/`max`, not both")
        return self


class TimelinessParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_age_hours: int = Field(gt=0)


CheckKind = Literal["completeness", "accuracy", "timeliness"]

PARAMS: dict[str, type[BaseModel]] = {
    "completeness": CompletenessParams,
    "accuracy": AccuracyParams,
    "timeliness": TimelinessParams,
}


class CheckDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: CheckKind
    field: str
    params: dict = {}

    @model_validator(mode="after")
    def valid_params(self) -> "CheckDeclaration":
        PARAMS[self.kind].model_validate(self.params)
        return self
