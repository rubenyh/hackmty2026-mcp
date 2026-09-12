"""Typed MCP inputs and structured outputs."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Self, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class UserScope(StrictModel):
    """Canonical user scope supplied by the application, never selected by the model."""

    user_id: UUID


class SelectRequest(StrictModel):
    """A structured, bounded table selection request."""

    schema_name: str = Field(alias="schema", min_length=1)
    table: str = Field(min_length=1)
    scope: UserScope
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


class VisualizationSource(StrictModel):
    """One reflected, allowlisted table or view used for a chart."""

    schema_name: str = Field(alias="schema", min_length=1)
    table: str = Field(min_length=1)


class AreaVisualization(StrictModel):
    """Column mapping for the existing multi-series area chart."""

    kind: Literal["area"]
    x_column: str = Field(min_length=1)
    y_columns: list[str] = Field(min_length=1, max_length=4)
    currency: Literal["MXN", "USD"] | None = None

    @model_validator(mode="after")
    def require_distinct_columns(self) -> Self:
        if len(set(self.y_columns)) != len(self.y_columns):
            raise ValueError("y_columns must not contain duplicates")
        if self.x_column in self.y_columns:
            raise ValueError("x_column must be distinct from y_columns")
        return self


class HeatmapVisualization(StrictModel):
    """Column mapping for the existing date/value calendar heatmap."""

    kind: Literal["heatmap"]
    date_column: str = Field(min_length=1)
    value_column: str = Field(min_length=1)
    initial_view: Literal["year", "month", "week"] = "month"
    currency: Literal["MXN", "USD"] | None = None

    @model_validator(mode="after")
    def require_distinct_columns(self) -> Self:
        if self.date_column == self.value_column:
            raise ValueError("date_column and value_column must be distinct")
        return self


VisualizationSpec = Annotated[
    AreaVisualization | HeatmapVisualization,
    Field(discriminator="kind"),
]


class VisualizeAllowedDataRequest(StrictModel):
    """Strict, bounded input for one domain-level visualization query."""

    scope: UserScope
    source: VisualizationSource
    filters: list[FilterCondition] = Field(default_factory=list, max_length=20)
    order: list[OrderBy] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=100, ge=1, le=500)
    title: str | None = Field(default=None, max_length=100)
    visualization: VisualizationSpec

    @model_validator(mode="after")
    def restrict_order_to_chart_columns(self) -> Self:
        visualization_columns = (
            {self.visualization.x_column, *self.visualization.y_columns}
            if isinstance(self.visualization, AreaVisualization)
            else {self.visualization.date_column, self.visualization.value_column}
        )
        if any(item.column not in visualization_columns for item in self.order):
            raise ValueError("order columns must be part of the visualization")
        return self


class AreaChartSeries(StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$")
    label: str = Field(min_length=1, max_length=80)
    tone: Literal["blue", "violet", "green", "orange"] | None = None


class AreaChartPoint(StrictModel):
    label: str = Field(min_length=1, max_length=80)
    values: list[Annotated[float, Field(ge=-1e15, le=1e15, allow_inf_nan=False)]] = Field(
        min_length=1, max_length=4
    )


class AreaChartProps(StrictModel):
    data: list[AreaChartPoint] = Field(max_length=240)
    series: list[AreaChartSeries] = Field(min_length=1, max_length=4)
    currency: Literal["MXN", "USD"] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if len({item.id for item in self.series}) != len(self.series):
            raise ValueError("series identifiers must be unique")
        if any(len(point.values) != len(self.series) for point in self.data):
            raise ValueError("each point must contain one value per series")
        if len({point.label for point in self.data}) != len(self.data):
            raise ValueError("area point labels must be unique")
        return self


class HeatmapChartCell(StrictModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    value: float = Field(ge=0, le=1e15, allow_inf_nan=False)

    @field_validator("date")
    @classmethod
    def validate_calendar_date(cls, value: str) -> str:
        from datetime import date

        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date must be a real calendar date") from exc
        if parsed.isoformat() != value or not date(1900, 1, 1) <= parsed <= date(2100, 12, 31):
            raise ValueError("date must be between 1900-01-01 and 2100-12-31")
        return value


class HeatmapChartProps(StrictModel):
    data: list[HeatmapChartCell] = Field(max_length=500)
    initial_date: str | None = Field(
        default=None, alias="initialDate", pattern=r"^\d{4}-\d{2}-\d{2}$"
    )
    initial_view: Literal["year", "month", "week"] = Field(alias="initialView")
    currency: Literal["MXN", "USD"] | None = None

    @model_validator(mode="after")
    def require_unique_dates(self) -> Self:
        if len({item.date for item in self.data}) != len(self.data):
            raise ValueError("heatmap dates must be unique")
        if self.initial_date is not None:
            HeatmapChartCell(date=self.initial_date, value=0)
        return self


class AreaChartData(StrictModel):
    kind: Literal["area"]
    accessible_summary: str = Field(alias="accessibleSummary", min_length=1, max_length=500)
    props: AreaChartProps


class HeatmapChartData(StrictModel):
    kind: Literal["heatmap"]
    accessible_summary: str = Field(alias="accessibleSummary", min_length=1, max_length=500)
    props: HeatmapChartProps


ChartData = Annotated[AreaChartData | HeatmapChartData, Field(discriminator="kind")]


class VisualizeAllowedDataResult(StrictModel):
    """Structured domain result returned alongside the optional A2UI surface."""

    ok: Literal[True]
    source: VisualizationSource
    row_count: int = Field(ge=0, le=500)
    omitted_null_rows: int = Field(ge=0, le=500)
    limit: int = Field(ge=1, le=500)
    truncated: bool
    chart: ChartData
