"""Budget-progress financial reads."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from supabase_mcp.database import DatabaseClient
from supabase_mcp.finance_models.budgets import BudgetProgressRequest
from supabase_mcp.models import FilterCondition, FilterOperator, OrderBy
from supabase_mcp.services.finance._shared import (
    _filters_for_accounts,
    _money,
    _owned_accounts,
    _require_owned_ids,
    _select,
)


async def get_budget_progress_data(
    database: DatabaseClient, request: BudgetProgressRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    await _require_owned_ids(database, request.scope, "budgets", "id", request.budget_ids)
    filters = [*_filters_for_accounts("account_id", request.account_ids)]
    if request.budget_ids:
        filters.append(
            FilterCondition(
                column="id",
                operator=FilterOperator.IN,
                value=[str(v) for v in request.budget_ids],
            )
        )
    if request.category:
        filters.append(
            FilterCondition(column="category", operator=FilterOperator.EQ, value=request.category)
        )
    rows, _ = await _select(
        database,
        request.scope,
        "budget_progress",
        [
            "id",
            "account_id",
            "name",
            "category",
            "currency",
            "limit_amount",
            "spent_amount",
            "remaining_amount",
            "progress_percentage",
            "start_date",
            "end_date",
            "status",
        ],
        filters=filters,
        order_by=[OrderBy(column="end_date")],
    )
    today = datetime.now(ZoneInfo(database.settings.timezone)).date()
    normalized = []
    for row in rows:
        completed = str(row.get("end_date")) < today.isoformat() or row.get("status") == "archived"
        if request.status == "active" and (completed or row.get("status") != "active"):
            continue
        if request.status == "completed" and not completed:
            continue
        if not request.include_expired and str(row.get("end_date")) < today.isoformat():
            continue
        normalized.append(
            {
                **row,
                "spent_amount": _money(row.get("spent_amount")),
                "remaining_amount": _money(row.get("remaining_amount")),
                "progress_percentage": _money(row.get("progress_percentage")),
            }
        )
    return {"ok": True, "budgets": normalized, "count": len(normalized)}


__all__ = ["get_budget_progress_data"]
