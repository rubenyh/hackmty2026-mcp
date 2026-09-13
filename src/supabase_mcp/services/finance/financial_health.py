"""Financial overview and alert reads."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

from supabase_mcp.database import DatabaseClient
from supabase_mcp.finance_models import (
    BudgetProgressRequest,
    CashFlowRequest,
    DebtOverviewRequest,
    FinancialAlertsRequest,
    FinancialOverviewRequest,
    SavingsProgressRequest,
)
from supabase_mcp.models import (
    FilterCondition,
    FilterOperator,
    FilterValue,
    OrderBy,
    OrderDirection,
)
from supabase_mcp.services.finance._shared import (
    _cursor_offset,
    _filters_for_accounts,
    _money,
    _next_cursor,
    _owned_accounts,
    _require_owned_ids,
    _select,
    resolve_period,
)
from supabase_mcp.services.finance.budgets import get_budget_progress_data
from supabase_mcp.services.finance.cash_flow import get_cash_flow_data
from supabase_mcp.services.finance.debts import get_debt_overview_data
from supabase_mcp.services.finance.savings import get_savings_progress_data


async def get_financial_alerts_data(
    database: DatabaseClient, request: FinancialAlertsRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    await _require_owned_ids(database, request.scope, "budgets", "id", request.budget_ids)
    filters = [*_filters_for_accounts("account_id", request.account_ids)]
    if request.status != "all":
        filters.append(
            FilterCondition(column="status", operator=FilterOperator.EQ, value=request.status)
        )
    if request.kinds:
        filters.append(
            FilterCondition(
                column="kind",
                operator=FilterOperator.IN,
                value=cast(FilterValue, request.kinds),
            )
        )
    if request.budget_ids:
        filters.append(
            FilterCondition(
                column="budget_id",
                operator=FilterOperator.IN,
                value=[str(v) for v in request.budget_ids],
            )
        )
    if request.due_within_days is not None:
        today = datetime.now(ZoneInfo(database.settings.timezone)).date()
        filters.extend(
            [
                FilterCondition(
                    column="due_date", operator=FilterOperator.GTE, value=today.isoformat()
                ),
                FilterCondition(
                    column="due_date",
                    operator=FilterOperator.LTE,
                    value=(today + timedelta(days=request.due_within_days)).isoformat(),
                ),
            ]
        )
    offset = _cursor_offset(request.cursor)
    rows, truncated = await _select(
        database,
        request.scope,
        "financial_alerts",
        [
            "id",
            "account_id",
            "budget_id",
            "title",
            "message",
            "kind",
            "threshold_amount",
            "due_date",
            "status",
            "created_at",
        ],
        filters=filters,
        order_by=[
            OrderBy(column="due_date"),
            OrderBy(column="created_at", direction=OrderDirection.DESC),
            OrderBy(column="id"),
        ],
        limit=request.limit,
        offset=offset,
    )
    return {
        "ok": True,
        "alerts": rows,
        "count": len(rows),
        "next_cursor": _next_cursor(offset, len(rows), truncated),
    }


async def get_financial_overview_data(
    database: DatabaseClient, request: FinancialOverviewRequest
) -> dict[str, Any]:
    accounts = await _owned_accounts(database, request.scope, request.account_ids)
    resolved = resolve_period(request.period, timezone_name=database.settings.timezone)
    cash_request = CashFlowRequest(
        scope=request.scope,
        period="custom",
        start_date=date.fromisoformat(resolved["start_date"]),
        end_date=date.fromisoformat(resolved["end_date"]),
        account_ids=request.account_ids,
    )
    cash = await get_cash_flow_data(database, cash_request)
    budgets = await get_budget_progress_data(
        database,
        BudgetProgressRequest(
            scope=request.scope, account_ids=request.account_ids, status="active"
        ),
    )
    savings = await get_savings_progress_data(
        database,
        SavingsProgressRequest(scope=request.scope, account_ids=request.account_ids, status="all"),
    )
    debts = await get_debt_overview_data(
        database,
        DebtOverviewRequest(
            scope=request.scope,
            account_ids=request.account_ids,
            status="active",
            include_scenarios=False,
        ),
    )
    alerts = await get_financial_alerts_data(
        database,
        FinancialAlertsRequest(
            scope=request.scope, account_ids=request.account_ids, status="active", limit=100
        ),
    )
    by_currency: defaultdict[str, dict[str, Decimal]] = defaultdict(
        lambda: {
            "available_balance": Decimal(),
            "income": Decimal(),
            "expenses": Decimal(),
            "net": Decimal(),
            "outstanding_debt": Decimal(),
            "saved_amount": Decimal(),
            "savings_target": Decimal(),
        }
    )
    for row in accounts:
        by_currency[str(row["currency"])]["available_balance"] += _money(row["available_balance"])
    for row in cash["totals_by_currency"]:
        for field in ("income", "expenses", "net"):
            by_currency[row["currency"]][field] += _money(row[field])
    for row in debts["totals_by_currency"]:
        by_currency[row["currency"]]["outstanding_debt"] += _money(
            row["outstanding_principal"]
        ) + _money(row["credit_card_debt"])
    for row in savings["goals"]:
        by_currency[str(row["currency"])]["saved_amount"] += _money(row["saved_amount"])
        by_currency[str(row["currency"])]["savings_target"] += _money(row["target_amount"])
    budget_rows = budgets["budgets"]
    next_dates = [row.get("next_due_date") for row in debts["debts"]] + [
        row.get("due_date") for row in debts["credit_cards"]
    ]
    next_dates = [value for value in next_dates if value]
    return {
        "ok": True,
        "as_of": datetime.now(ZoneInfo(database.settings.timezone)).date().isoformat(),
        "period": resolved,
        "filters_applied": {"account_ids": [str(v) for v in request.account_ids]},
        "currencies": [
            {"currency": currency, **values} for currency, values in sorted(by_currency.items())
        ],
        "budgets": {
            "active_count": len(budget_rows),
            "over_limit_count": sum(_money(row["remaining_amount"]) < 0 for row in budget_rows),
            "near_limit_count": sum(
                Decimal("80") <= _money(row["progress_percentage"]) <= Decimal("100")
                for row in budget_rows
            ),
        },
        "next_obligation": min(map(str, next_dates)) if next_dates else None,
        "active_alerts_count": alerts["count"],
    }


__all__ = ["get_financial_alerts_data", "get_financial_overview_data"]
