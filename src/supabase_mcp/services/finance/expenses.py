"""Transaction, spending-analysis, and dispute financial reads."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from supabase_mcp.database import DatabaseClient
from supabase_mcp.errors import SafeMCPError
from supabase_mcp.finance_models.expenses import (
    SpendingAnalysisRequest,
    TransactionDisputesRequest,
    TransactionsRequest,
)
from supabase_mcp.models import (
    FilterCondition,
    FilterOperator,
    FilterValue,
    OrderBy,
    OrderDirection,
)
from supabase_mcp.services.finance._shared import (
    _currency_map,
    _cursor_offset,
    _filters_for_accounts,
    _iso_date,
    _money,
    _next_cursor,
    _owned_accounts,
    _period_filters,
    _require_owned_ids,
    _select,
    resolve_period,
)


async def get_transactions_data(
    database: DatabaseClient, request: TransactionsRequest
) -> dict[str, Any]:
    accounts = await _owned_accounts(database, request.scope, request.account_ids)
    account_ids = request.account_ids or [UUID(str(row["id"])) for row in accounts]
    resolved = resolve_period(
        request.period,
        timezone_name=database.settings.timezone,
        start_date=request.start_date,
        end_date=request.end_date,
    )
    filters = [
        *_period_filters("occurred_at", resolved, timestamp=True),
        *_filters_for_accounts("account_id", account_ids),
    ]
    if request.direction:
        filters.append(
            FilterCondition(
                column="direction",
                operator=FilterOperator.EQ,
                value="credit" if request.direction == "income" else "debit",
            )
        )
    if request.categories:
        filters.append(
            FilterCondition(
                column="category",
                operator=FilterOperator.IN,
                value=cast(FilterValue, request.categories),
            )
        )
    if request.merchant_query:
        filters.append(
            FilterCondition(
                column="merchant",
                operator=FilterOperator.ILIKE,
                value=f"%{request.merchant_query}%",
            )
        )
    if request.min_amount is not None:
        filters.append(
            FilterCondition(
                column="amount", operator=FilterOperator.GTE, value=str(request.min_amount)
            )
        )
    if request.max_amount is not None:
        filters.append(
            FilterCondition(
                column="amount", operator=FilterOperator.LTE, value=str(request.max_amount)
            )
        )
    order_column = "amount" if request.order in {"highest", "lowest"} else "occurred_at"
    order_direction = (
        OrderDirection.DESC if request.order in {"newest", "highest"} else OrderDirection.ASC
    )
    offset = _cursor_offset(request.cursor)
    rows, truncated = await _select(
        database,
        request.scope,
        "transactions",
        ["id", "account_id", "amount", "direction", "category", "merchant", "occurred_at"],
        filters=filters,
        order_by=[
            OrderBy(column=order_column, direction=order_direction),
            OrderBy(column="id", direction=order_direction),
        ],
        limit=request.limit,
        offset=offset,
    )
    currencies = _currency_map(accounts)
    summary: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)
    transactions = []
    for row in rows:
        currency = currencies.get(str(row["account_id"]))
        if currency is None:
            raise SafeMCPError("invalid_data", "A transaction account currency is unavailable.")
        direction = "income" if row.get("direction") == "credit" else "expense"
        summary[(currency, direction)] += _money(row.get("amount"))
        transactions.append({**row, "direction": direction, "currency": currency})
    summary_rows = [
        {
            "currency": currency,
            "income": summary[(currency, "income")],
            "expenses": summary[(currency, "expense")],
        }
        for currency in sorted({key[0] for key in summary})
    ]
    return {
        "ok": True,
        "period": resolved,
        "filters_applied": {
            "account_ids": [str(value) for value in request.account_ids],
            "categories": request.categories,
            "merchant_query": request.merchant_query,
            "direction": request.direction,
        },
        "summary_by_currency": summary_rows,
        "transactions": transactions,
        "next_cursor": _next_cursor(offset, len(rows), truncated),
    }


async def analyze_spending_data(
    database: DatabaseClient, request: SpendingAnalysisRequest
) -> dict[str, Any]:
    accounts = await _owned_accounts(database, request.scope, request.account_ids)
    account_ids = request.account_ids or [UUID(str(row["id"])) for row in accounts]
    resolved = resolve_period(
        request.period,
        timezone_name=database.settings.timezone,
        start_date=request.start_date,
        end_date=request.end_date,
    )

    async def read_range(period: Mapping[str, Any]) -> list[dict[str, Any]]:
        filters = [
            *_period_filters("occurred_at", period, timestamp=True),
            *_filters_for_accounts("account_id", account_ids),
            FilterCondition(column="direction", operator=FilterOperator.EQ, value="debit"),
        ]
        if request.categories:
            filters.append(
                FilterCondition(
                    column="category",
                    operator=FilterOperator.IN,
                    value=cast(FilterValue, request.categories),
                )
            )
        rows, _ = await _select(
            database,
            request.scope,
            "transactions",
            ["id", "account_id", "amount", "category", "merchant", "occurred_at"],
            filters=filters,
            order_by=[OrderBy(column="occurred_at")],
        )
        return rows

    rows = await read_range(resolved)
    previous: dict[str, Any] | None = None
    previous_rows: list[dict[str, Any]] = []
    if request.compare_with_previous_period:
        start = date.fromisoformat(resolved["start_date"])
        end = date.fromisoformat(resolved["end_date"])
        days = (end - start).days + 1
        previous = {
            "start_date": (start - timedelta(days=days)).isoformat(),
            "end_date": (start - timedelta(days=1)).isoformat(),
            "end_inclusive": True,
            "timezone": database.settings.timezone,
        }
        previous_rows = await read_range(previous)
    currencies = _currency_map(accounts)
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    prior_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    category_totals: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)
    daily_totals: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)
    merchant_totals: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for row in rows:
        currency = currencies[str(row["account_id"])]
        amount = _money(row["amount"])
        totals[currency] += amount
        category_totals[(currency, str(row.get("category") or "uncategorized"))] += amount
        day = _iso_date(row.get("occurred_at")) or "unknown"
        daily_totals[(currency, day)] += amount
        merchant_totals[(currency, str(row.get("merchant") or "Unknown"))] += amount
    for row in previous_rows:
        prior_totals[currencies[str(row["account_id"])]] += _money(row["amount"])
    summary = []
    for currency in sorted(set(totals) | set(prior_totals)):
        current, prior = totals[currency], prior_totals[currency]
        change = None if prior == 0 else ((current - prior) / prior * Decimal("100"))
        summary.append(
            {
                "currency": currency,
                "expenses": current,
                "previous_expenses": prior,
                "change_percentage": change,
            }
        )
    return {
        "ok": True,
        "period": resolved,
        "comparison_period": previous,
        "summary_by_currency": summary,
        "by_category": [
            {"currency": c, "category": category, "amount": amount}
            for (c, category), amount in sorted(
                category_totals.items(), key=lambda item: (item[0][0], -item[1], item[0][1])
            )
        ],
        "daily_series": [
            {"currency": c, "date": day, "amount": amount}
            for (c, day), amount in sorted(daily_totals.items())
        ]
        if request.include_daily_series
        else [],
        "top_merchants": [
            {"currency": c, "merchant": merchant, "amount": amount}
            for (c, merchant), amount in sorted(
                merchant_totals.items(), key=lambda item: (item[0][0], -item[1], item[0][1])
            )[: request.top_merchants_limit]
        ]
        if request.include_top_merchants
        else [],
        "data_quality": {"complete": True, "warnings": []},
    }


async def get_transaction_disputes_data(
    database: DatabaseClient, request: TransactionDisputesRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    await _require_owned_ids(database, request.scope, "transactions", "id", request.transaction_ids)
    filters = [*_filters_for_accounts("account_id", request.account_ids)]
    if request.period is not None:
        resolved = resolve_period(request.period, timezone_name=database.settings.timezone)
        filters.extend(_period_filters("created_at", resolved, timestamp=True))
    if request.statuses:
        filters.append(
            FilterCondition(
                column="status",
                operator=FilterOperator.IN,
                value=cast(FilterValue, request.statuses),
            )
        )
    if request.transaction_ids:
        filters.append(
            FilterCondition(
                column="transaction_id",
                operator=FilterOperator.IN,
                value=[str(v) for v in request.transaction_ids],
            )
        )
    offset = _cursor_offset(request.cursor)
    disputes, truncated = await _select(
        database,
        request.scope,
        "transaction_disputes",
        [
            "id",
            "account_id",
            "transaction_id",
            "card_id",
            "reason",
            "status",
            "resolution",
            "created_at",
        ],
        filters=filters,
        order_by=[
            OrderBy(column="created_at", direction=OrderDirection.DESC),
            OrderBy(column="id", direction=OrderDirection.DESC),
        ],
        limit=request.limit,
        offset=offset,
    )
    transaction_ids = [str(row["transaction_id"]) for row in disputes]
    transactions: list[dict[str, Any]] = []
    if transaction_ids:
        transactions, _ = await _select(
            database,
            request.scope,
            "transactions",
            ["id", "account_id", "amount", "direction", "category", "merchant", "occurred_at"],
            filters=[
                FilterCondition(
                    column="id",
                    operator=FilterOperator.IN,
                    value=cast(FilterValue, transaction_ids),
                )
            ],
        )
    by_id = {str(row["id"]): row for row in transactions}
    results = [{**row, "transaction": by_id.get(str(row["transaction_id"]))} for row in disputes]
    return {
        "ok": True,
        "disputes": results,
        "count": len(results),
        "next_cursor": _next_cursor(offset, len(results), truncated),
    }


__all__ = [
    "analyze_spending_data",
    "get_transaction_disputes_data",
    "get_transactions_data",
]
