"""Bounded domain mapping from allowlisted database rows to trusted chart data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Literal

from supabase_mcp.database import DatabaseClient
from supabase_mcp.models import (
    AreaChartData,
    AreaChartPoint,
    AreaChartProps,
    AreaChartSeries,
    AreaVisualization,
    HeatmapChartCell,
    HeatmapChartData,
    HeatmapChartProps,
    OrderBy,
    SelectRequest,
    VisualizeAllowedDataRequest,
    VisualizeAllowedDataResult,
)

AREA_MAX_ROWS = 240
HEATMAP_MAX_ROWS = 500
_TONES: tuple[Literal["blue"], Literal["violet"], Literal["green"], Literal["orange"]] = (
    "blue",
    "violet",
    "green",
    "orange",
)


class ChartMappingError(ValueError):
    """A database result cannot be represented by the trusted chart contract."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def _numeric(value: Any, *, nonnegative: bool) -> float:
    if isinstance(value, bool) or value is None:
        raise ChartMappingError("invalid_numeric_value", "A chart value is not numeric.")
    try:
        number = float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError, OverflowError) as exc:
        raise ChartMappingError("invalid_numeric_value", "A chart value is not numeric.") from exc
    if not isfinite(number) or abs(number) > 1e15 or (nonnegative and number < 0):
        raise ChartMappingError(
            "invalid_numeric_value", "A chart value is outside the supported numeric range."
        )
    return number


def _label(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        raise ChartMappingError("invalid_label", "A chart label is not a JSON-safe scalar.")
    if isinstance(value, float) and not isfinite(value):
        raise ChartMappingError("invalid_label", "A chart label is not finite.")
    if isinstance(value, bool):
        label = "true" if value else "false"
    elif isinstance(value, str | int | float):
        label = str(value)
    else:
        raise ChartMappingError("invalid_label", "A chart label is not a JSON-safe scalar.")
    if not label or len(label) > 80:
        raise ChartMappingError("invalid_label", "A chart label is outside the supported bounds.")
    return label


def _calendar_date(value: Any) -> str:
    if isinstance(value, date):
        if not date(1900, 1, 1) <= value <= date(2100, 12, 31):
            raise ChartMappingError("invalid_date", "A heatmap date is outside 1900 through 2100.")
        return value.isoformat()
    if not isinstance(value, str) or len(value) != 10:
        raise ChartMappingError("invalid_date", "A heatmap date must use YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ChartMappingError("invalid_date", "A heatmap date is invalid.") from exc
    if parsed.isoformat() != value or not date(1900, 1, 1) <= parsed <= date(2100, 12, 31):
        raise ChartMappingError("invalid_date", "A heatmap date is outside 1900 through 2100.")
    return value


def _required_columns(request: VisualizeAllowedDataRequest) -> list[str]:
    visualization = request.visualization
    if isinstance(visualization, AreaVisualization):
        return [visualization.x_column, *visualization.y_columns]
    return [visualization.date_column, visualization.value_column]


async def get_data_chart(
    database: DatabaseClient, request: VisualizeAllowedDataRequest
) -> VisualizeAllowedDataResult:
    """Query only required columns and map the bounded result to one chart variant."""
    visualization = request.visualization
    columns = _required_columns(request)
    if set(columns) & database.user_scope_columns(request.source.schema_name, request.source.table):
        raise ChartMappingError(
            "ownership_column_not_visualizable",
            "Ownership identifiers cannot be used as chart data.",
        )
    numeric_columns = (
        visualization.y_columns
        if isinstance(visualization, AreaVisualization)
        else [visualization.value_column]
    )
    database.require_numeric_columns(
        request.source.schema_name, request.source.table, numeric_columns
    )
    maximum = AREA_MAX_ROWS if isinstance(visualization, AreaVisualization) else HEATMAP_MAX_ROWS
    effective_limit = min(request.limit, database.settings.max_limit, maximum)
    ordering = request.order or [
        OrderBy(
            column=(
                visualization.x_column
                if isinstance(visualization, AreaVisualization)
                else visualization.date_column
            )
        )
    ]
    rows, _limit, truncated = await database.select_scoped_rows(
        SelectRequest(
            schema=request.source.schema_name,
            table=request.source.table,
            scope=request.scope,
            columns=columns,
            filters=request.filters,
            order_by=ordering,
            limit=effective_limit,
        )
    )

    omitted = 0
    if isinstance(visualization, AreaVisualization):
        points: list[AreaChartPoint] = []
        labels: set[str] = set()
        for row in rows:
            values = [row.get(column) for column in columns]
            if any(value is None for value in values):
                omitted += 1
                continue
            label = _label(values[0])
            if label in labels:
                raise ChartMappingError(
                    "duplicate_label", "Area chart labels must be unique after mapping."
                )
            labels.add(label)
            points.append(
                AreaChartPoint(
                    label=label,
                    values=[_numeric(value, nonnegative=False) for value in values[1:]],
                )
            )
        series = [
            AreaChartSeries(id=f"series_{index + 1}", label=column, tone=_TONES[index])
            for index, column in enumerate(visualization.y_columns)
        ]
        summary = (
            f"Area chart with {len(points)} points and {len(series)} series."
            if points
            else "Area chart with no data for the selected rows."
        )
        chart: AreaChartData | HeatmapChartData = AreaChartData(
            kind="area",
            accessibleSummary=summary,
            props=AreaChartProps(
                data=points,
                series=series,
                currency=visualization.currency,
            ),
        )
    else:
        cells: list[HeatmapChartCell] = []
        seen_dates: set[str] = set()
        for row in rows:
            raw_date = row.get(visualization.date_column)
            raw_value = row.get(visualization.value_column)
            if raw_date is None or raw_value is None:
                omitted += 1
                continue
            cell_date = _calendar_date(raw_date)
            if cell_date in seen_dates:
                raise ChartMappingError(
                    "duplicate_date", "Heatmap dates must be unique after mapping."
                )
            seen_dates.add(cell_date)
            cells.append(
                HeatmapChartCell(date=cell_date, value=_numeric(raw_value, nonnegative=True))
            )
        summary = (
            f"Calendar heatmap with {len(cells)} dated values."
            if cells
            else "Calendar heatmap with no data for the selected rows."
        )
        chart = HeatmapChartData(
            kind="heatmap",
            accessibleSummary=summary,
            props=HeatmapChartProps(
                data=cells,
                initialDate=cells[-1].date if cells else None,
                initialView=visualization.initial_view,
                currency=visualization.currency,
            ),
        )

    return VisualizeAllowedDataResult(
        ok=True,
        source=request.source,
        row_count=len(rows) - omitted,
        omitted_null_rows=omitted,
        limit=effective_limit,
        truncated=truncated,
        chart=chart,
    )


def chart_data_model(result: VisualizeAllowedDataResult, title: str | None) -> dict[str, Any]:
    """Create the exact dynamic fields bound by the static chart surface."""
    resolved_title = title or f"{result.source.schema_name}.{result.source.table} data chart"
    chart = result.chart.model_dump(mode="json", by_alias=True, exclude_none=True)
    return {
        "title": resolved_title,
        "summary": result.chart.accessible_summary,
        "chart": chart,
    }


def chart_fallback(result: VisualizeAllowedDataResult) -> str:
    """Return useful text for clients that ignore the A2UI embedded resource."""
    omitted = (
        f" {result.omitted_null_rows} row(s) with null required values were omitted."
        if result.omitted_null_rows
        else ""
    )
    truncated = " The raw query was truncated." if result.truncated else ""
    return f"{result.chart.accessible_summary}{omitted}{truncated}"


__all__ = [
    "AREA_MAX_ROWS",
    "HEATMAP_MAX_ROWS",
    "ChartMappingError",
    "chart_data_model",
    "chart_fallback",
    "get_data_chart",
]
