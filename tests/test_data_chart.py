"""Offline contract tests for bounded allowlisted chart mapping."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from supabase_mcp.errors import InvalidSelectionError
from supabase_mcp.models import (
    AreaChartData,
    HeatmapChartData,
    VisualizeAllowedDataRequest,
)
from supabase_mcp.services.data_chart import ChartMappingError, get_data_chart

USER_A = "68dc4d66-07b8-5893-95f1-07f06989a552"
USER_B = "c1a3797d-b335-5a9d-98a1-402311f82c7a"


class FakeDatabase:
    def __init__(self, rows: list[dict[str, Any]], *, numeric: bool = True) -> None:
        self.rows = rows
        self.numeric = numeric
        self.settings = SimpleNamespace(max_limit=500)
        self.numeric_check: tuple[str, str, list[str]] | None = None
        self.request: Any = None

    def require_numeric_columns(self, schema: str, table: str, names: list[str]) -> None:
        self.numeric_check = (schema, table, names)
        if not self.numeric:
            raise InvalidSelectionError(
                "column_not_numeric", "A chart value column is not numeric."
            )

    def user_scope_columns(self, schema: str, table: str) -> frozenset[str]:
        del schema, table
        return frozenset()

    async def select_rows(self, request: Any) -> tuple[list[dict[str, Any]], int, bool]:
        self.request = request
        return self.rows, request.limit, len(self.rows) > request.limit


def area_request(*, limit: int = 100) -> VisualizeAllowedDataRequest:
    return VisualizeAllowedDataRequest.model_validate(
        {
            "scope": {"user_id": USER_A},
            "source": {"schema": "public", "table": "cashflow"},
            "limit": limit,
            "visualization": {
                "kind": "area",
                "x_column": "month",
                "y_columns": ["income", "spend"],
            },
        }
    )


@pytest.mark.asyncio
async def test_area_mapping_queries_only_required_columns_and_omits_null_rows() -> None:
    database = FakeDatabase(
        [
            {"month": "Jan", "income": 10, "spend": -2.5},
            {"month": "Feb", "income": None, "spend": 3},
        ]
    )
    result = await get_data_chart(database, area_request())  # type: ignore[arg-type]

    assert database.numeric_check == ("public", "cashflow", ["income", "spend"])
    assert database.request.columns == ["month", "income", "spend"]
    assert [item.column for item in database.request.order_by] == ["month"]
    assert result.row_count == 1
    assert result.omitted_null_rows == 1
    assert isinstance(result.chart, AreaChartData)
    assert result.chart.props.data[0].values == [10.0, -2.5]


@pytest.mark.asyncio
async def test_heatmap_accepts_database_dates_and_enforces_nonnegative_values() -> None:
    request = VisualizeAllowedDataRequest.model_validate(
        {
            "scope": {"user_id": USER_A},
            "source": {"schema": "analytics", "table": "daily_activity"},
            "limit": 500,
            "visualization": {
                "kind": "heatmap",
                "date_column": "day",
                "value_column": "amount",
            },
        }
    )
    database = FakeDatabase([{"day": date(2026, 9, 12), "amount": 42.5}])
    result = await get_data_chart(database, request)  # type: ignore[arg-type]
    assert isinstance(result.chart, HeatmapChartData)
    assert result.chart.props.data[0].date == "2026-09-12"

    database.rows = [{"day": "2026-09-12", "amount": -1}]
    with pytest.raises(ChartMappingError, match="supported numeric range"):
        await get_data_chart(database, request)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_area_limit_is_clamped_and_nonnumeric_metadata_fails_before_query() -> None:
    database = FakeDatabase([])
    result = await get_data_chart(database, area_request(limit=500))  # type: ignore[arg-type]
    assert result.limit == 240
    assert database.request.limit == 240

    rejected = FakeDatabase([], numeric=False)
    with pytest.raises(InvalidSelectionError, match="not numeric"):
        await get_data_chart(rejected, area_request())  # type: ignore[arg-type]
    assert rejected.request is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "source": {"schema": "public", "table": "cashflow"},
            "visualization": {"kind": "pie", "x_column": "x", "y_columns": ["y"]},
        },
        {
            "source": {"schema": "public", "table": "cashflow"},
            "visualization": {
                "kind": "area",
                "x_column": "x",
                "y_columns": ["y"],
                "style": {"color": "red"},
            },
        },
    ],
)
def test_request_rejects_unknown_shapes_and_properties(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VisualizeAllowedDataRequest.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "user_id", "expected", "expected_transactions"),
    [
        ("area", USER_A, ["2026-09-10", "2026-09-11"], ["A1", "A2"]),
        ("area", USER_B, ["2026-09-12", "2026-09-13"], ["B1", "B2"]),
        ("heatmap", USER_A, ["2026-09-10", "2026-09-11"], ["A1", "A2"]),
        ("heatmap", USER_B, ["2026-09-12", "2026-09-13"], ["B1", "B2"]),
    ],
)
async def test_area_and_heatmap_rows_are_isolated_by_scope(
    kind: str, user_id: str, expected: list[str], expected_transactions: list[str]
) -> None:
    class ScopedDatabase(FakeDatabase):
        def __init__(self, rows: list[dict[str, Any]]) -> None:
            super().__init__(rows)
            self.selected_transactions: list[str] = []

        def user_scope_columns(self, schema: str, table: str) -> frozenset[str]:
            del schema, table
            return frozenset({"account_id"})

        async def select_rows(self, request: Any) -> tuple[list[dict[str, Any]], int, bool]:
            self.request = request
            owned_rows = [row for row in self.rows if row["owner"] == str(request.scope.user_id)]
            self.selected_transactions = [str(row["transaction"]) for row in owned_rows]
            selected = [{column: row[column] for column in request.columns} for row in owned_rows]
            return selected, request.limit, False

    database = ScopedDatabase(
        [
            {"transaction": "A1", "owner": USER_A, "day": "2026-09-10", "amount": 10},
            {"transaction": "A2", "owner": USER_A, "day": "2026-09-11", "amount": 20},
            {"transaction": "B1", "owner": USER_B, "day": "2026-09-12", "amount": 30},
            {"transaction": "B2", "owner": USER_B, "day": "2026-09-13", "amount": 40},
        ]
    )
    visualization = (
        {"kind": "area", "x_column": "day", "y_columns": ["amount"]}
        if kind == "area"
        else {"kind": "heatmap", "date_column": "day", "value_column": "amount"}
    )
    request = VisualizeAllowedDataRequest.model_validate(
        {
            "scope": {"user_id": user_id},
            "source": {"schema": "public", "table": "transactions"},
            "visualization": visualization,
        }
    )

    result = await get_data_chart(database, request)  # type: ignore[arg-type]
    actual = (
        [point.label for point in result.chart.props.data]
        if isinstance(result.chart, AreaChartData)
        else [cell.date for cell in result.chart.props.data]
    )
    assert actual == expected
    assert database.selected_transactions == expected_transactions


@pytest.mark.asyncio
async def test_ownership_identifier_cannot_be_visualized() -> None:
    class ScopedDatabase(FakeDatabase):
        def user_scope_columns(self, schema: str, table: str) -> frozenset[str]:
            del schema, table
            return frozenset({"account_id"})

    request = VisualizeAllowedDataRequest.model_validate(
        {
            "scope": {"user_id": USER_A},
            "source": {"schema": "public", "table": "transactions"},
            "visualization": {
                "kind": "area",
                "x_column": "account_id",
                "y_columns": ["amount"],
            },
        }
    )
    with pytest.raises(ChartMappingError) as caught:
        await get_data_chart(ScopedDatabase([]), request)  # type: ignore[arg-type]
    assert caught.value.code == "ownership_column_not_visualizable"
