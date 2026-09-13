"""Savings-progress financial reads."""

from __future__ import annotations

from typing import Any, cast

from supabase_mcp.database import DatabaseClient
from supabase_mcp.finance_models.savings import SavingsProgressRequest
from supabase_mcp.models import (
    FilterCondition,
    FilterOperator,
    FilterValue,
    OrderBy,
    OrderDirection,
)
from supabase_mcp.services.finance._shared import (
    _filters_for_accounts,
    _owned_accounts,
    _require_owned_ids,
    _select,
)


async def get_savings_progress_data(
    database: DatabaseClient, request: SavingsProgressRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    await _require_owned_ids(database, request.scope, "savings_goals", "id", request.goal_ids)
    filters = [*_filters_for_accounts("account_id", request.account_ids)]
    if request.goal_ids:
        filters.append(
            FilterCondition(
                column="id",
                operator=FilterOperator.IN,
                value=[str(v) for v in request.goal_ids],
            )
        )
    rows, _ = await _select(
        database,
        request.scope,
        "savings_goal_progress",
        [
            "id",
            "account_id",
            "name",
            "currency",
            "target_amount",
            "saved_amount",
            "remaining_amount",
            "progress_percentage",
            "target_date",
            "suggested_monthly_contribution",
            "status",
        ],
        filters=filters,
        order_by=[OrderBy(column="target_date")],
    )
    goals = [row for row in rows if request.status == "all" or row.get("status") == request.status]
    contributions: list[dict[str, Any]] = []
    if request.include_contributions:
        selected_ids = [str(row["id"]) for row in goals]
        if selected_ids:
            contributions, _ = await _select(
                database,
                request.scope,
                "savings_contributions",
                ["id", "goal_id", "amount", "contributed_at", "note"],
                filters=[
                    FilterCondition(
                        column="goal_id",
                        operator=FilterOperator.IN,
                        value=cast(FilterValue, selected_ids),
                    )
                ],
                order_by=[OrderBy(column="contributed_at", direction=OrderDirection.DESC)],
                limit=request.contributions_limit,
            )
    return {"ok": True, "goals": goals, "contributions": contributions, "count": len(goals)}


__all__ = ["get_savings_progress_data"]
