"""Typed MCP inputs and structured outputs."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects accidental or misspelled fields."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


class FilterOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    LIKE = "like"
    ILIKE = "ilike"
    IS_NULL = "is_null"


class OrderDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


JsonScalar: TypeAlias = str | int | float | bool | None
JsonScalarList: TypeAlias = Annotated[list[JsonScalar], Field(min_length=1, max_length=100)]
FilterValue: TypeAlias = JsonScalar | JsonScalarList


class FilterCondition(StrictModel):
    """One allowlisted comparison applied to a reflected column."""

    column: str = Field(min_length=1, description="Reflected column name")
    operator: FilterOperator
    value: FilterValue = Field(default=None, description="JSON-safe scalar or bounded scalar list")

    @model_validator(mode="after")
    def validate_operator_value(self) -> Self:
        if self.operator is FilterOperator.IN:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError("the in operator requires a non-empty list value")
        elif self.operator is FilterOperator.IS_NULL:
            if not isinstance(self.value, bool):
                raise ValueError("the is_null operator requires a boolean value")
        elif isinstance(self.value, (list, dict)):
            raise ValueError(f"the {self.operator.value} operator requires a scalar value")
        return self


class OrderBy(StrictModel):
    """A validated ordering term."""

    column: str = Field(min_length=1)
    direction: OrderDirection = OrderDirection.ASC


class SelectRequest(StrictModel):
    """A structured, bounded table selection request."""

    schema_name: str = Field(alias="schema", min_length=1)
    table: str = Field(min_length=1)
    columns: list[str] | None = None
    filters: list[FilterCondition] = Field(default_factory=list)
    order_by: list[OrderBy] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1)
    offset: int = Field(default=0, ge=0)


class PublicError(StrictModel):
    code: str
    message: str


class HealthResult(StrictModel):
    ok: bool
    status: str
    database_available: bool
    error: PublicError | None = None


class AllowedObject(StrictModel):
    schema_name: str = Field(alias="schema")
    table: str
    kind: str


class AllowedTablesResult(StrictModel):
    ok: bool
    objects: list[AllowedObject] = Field(default_factory=list)
    object_count: int = 0
    error: PublicError | None = None


class ColumnDescription(StrictModel):
    name: str
    data_type: str
    nullable: bool
    primary_key: bool


class DescribeTableResult(StrictModel):
    ok: bool
    schema_name: str = Field(alias="schema")
    table: str
    columns: list[ColumnDescription] = Field(default_factory=list)
    error: PublicError | None = None


class SelectResult(StrictModel):
    ok: bool
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    limit: int
    offset: int
    truncated: bool = False
    error: PublicError | None = None
