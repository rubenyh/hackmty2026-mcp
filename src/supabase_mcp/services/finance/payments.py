"""Upcoming and historical payment financial reads."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from supabase_mcp.database import DatabaseClient
from supabase_mcp.finance_models.payments import (
    BeneficiariesRequest,
    PaymentActivityRequest,
    UpcomingPaymentsRequest,
)
from supabase_mcp.models import FilterCondition, FilterOperator, OrderBy, OrderDirection
from supabase_mcp.services.finance._shared import (
    _cursor_offset,
    _filters_for_accounts,
    _next_cursor,
    _owned_accounts,
    _period_filters,
    _select,
    _sum_by_currency,
    resolve_period,
)


async def get_upcoming_payments_data(
    database: DatabaseClient, request: UpcomingPaymentsRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    today = datetime.now(ZoneInfo(database.settings.timezone)).date()
    through = today + timedelta(days=request.days_ahead)
    date_filters = [
        FilterCondition(
            column="scheduled_date", operator=FilterOperator.GTE, value=today.isoformat()
        ),
        FilterCondition(
            column="scheduled_date", operator=FilterOperator.LTE, value=through.isoformat()
        ),
    ]
    scheduled, _ = await _select(
        database,
        request.scope,
        "scheduled_cash_flows",
        ["id", "account_id", "name", "direction", "amount", "currency", "scheduled_date", "status"],
        filters=[*date_filters, *_filters_for_accounts("account_id", request.account_ids)],
    )
    subscriptions, _ = await _select(
        database,
        request.scope,
        "subscriptions",
        ["id", "name", "amount", "next_charge_date", "status"],
        filters=[
            FilterCondition(
                column="next_charge_date", operator=FilterOperator.GTE, value=today.isoformat()
            ),
            FilterCondition(
                column="next_charge_date", operator=FilterOperator.LTE, value=through.isoformat()
            ),
        ],
    )
    debts, _ = await _select(
        database,
        request.scope,
        "debts",
        ["id", "account_id", "name", "monthly_payment", "currency", "next_due_date", "status"],
        filters=[
            FilterCondition(
                column="next_due_date", operator=FilterOperator.GTE, value=today.isoformat()
            ),
            FilterCondition(
                column="next_due_date", operator=FilterOperator.LTE, value=through.isoformat()
            ),
            *_filters_for_accounts("account_id", request.account_ids),
        ],
    )
    terms, _ = await _select(
        database,
        request.scope,
        "credit_card_terms",
        ["id", "account_id", "interest_free_payment", "currency", "due_date", "as_of"],
        filters=[
            FilterCondition(
                column="due_date", operator=FilterOperator.GTE, value=today.isoformat()
            ),
            FilterCondition(
                column="due_date", operator=FilterOperator.LTE, value=through.isoformat()
            ),
            *_filters_for_accounts("account_id", request.account_ids),
        ],
        order_by=[OrderBy(column="as_of", direction=OrderDirection.DESC)],
    )
    orders, _ = await _select(
        database,
        request.scope,
        "payment_orders",
        ["id", "from_account_id", "kind", "amount", "currency", "requested_date", "status"],
        filters=[
            FilterCondition(
                column="requested_date", operator=FilterOperator.GTE, value=today.isoformat()
            ),
            FilterCondition(
                column="requested_date", operator=FilterOperator.LTE, value=through.isoformat()
            ),
            *_filters_for_accounts("from_account_id", request.account_ids),
        ],
    )
    items: list[dict[str, Any]] = []
    for row in scheduled:
        if row["direction"] == "income" and not request.include_expected_income:
            continue
        items.append(
            {
                "id": row["id"],
                "source": "scheduled_cash_flow",
                "name": row["name"],
                "direction": row["direction"],
                "amount": row["amount"],
                "currency": row["currency"],
                "due_date": row["scheduled_date"],
                "status": row["status"],
                "account_id": row["account_id"],
            }
        )
    for row in subscriptions:
        items.append(
            {
                "id": row["id"],
                "source": "subscription",
                "name": row["name"],
                "direction": "expense",
                "amount": row["amount"],
                "currency": None,
                "due_date": row["next_charge_date"],
                "status": row["status"],
                "account_id": None,
            }
        )
    for row in debts:
        items.append(
            {
                "id": row["id"],
                "source": "debt",
                "name": row["name"],
                "direction": "expense",
                "amount": row["monthly_payment"],
                "currency": row["currency"],
                "due_date": row["next_due_date"],
                "status": row["status"],
                "account_id": row["account_id"],
            }
        )
    seen_terms: set[str] = set()
    for row in terms:
        if str(row["account_id"]) in seen_terms:
            continue
        seen_terms.add(str(row["account_id"]))
        items.append(
            {
                "id": row["id"],
                "source": "credit_card",
                "name": "Credit card payment / Pago de tarjeta",
                "direction": "expense",
                "amount": row["interest_free_payment"],
                "currency": row["currency"],
                "due_date": row["due_date"],
                "status": "due",
                "account_id": row["account_id"],
            }
        )
    for row in orders:
        if row["status"] == "draft" and not request.include_drafts:
            continue
        items.append(
            {
                "id": row["id"],
                "source": "payment_order",
                "name": str(row["kind"]).replace("_", " "),
                "direction": "expense",
                "amount": row["amount"],
                "currency": row["currency"],
                "due_date": row["requested_date"],
                "status": row["status"],
                "account_id": row["from_account_id"],
            }
        )
    items.sort(key=lambda item: (str(item.get("due_date") or "9999-12-31"), str(item["id"])))
    return {
        "ok": True,
        "as_of": today.isoformat(),
        "through": through.isoformat(),
        "totals_by_currency": _sum_by_currency(items, "currency", "amount"),
        "items": items,
        "data_quality": {
            "complete": not bool(subscriptions),
            "warnings": [
                "Subscriptions have no currency or account in the source schema. / "
                "Las suscripciones no tienen moneda ni cuenta en el esquema origen."
            ]
            if subscriptions
            else [],
        },
    }


async def get_payment_activity_data(
    database: DatabaseClient, request: PaymentActivityRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    resolved = resolve_period(
        request.period,
        timezone_name=database.settings.timezone,
        start_date=request.start_date,
        end_date=request.end_date,
    )
    transfers, _ = await _select(
        database,
        request.scope,
        "transfers",
        ["id", "from_account_id", "to_account_id", "amount", "status", "note", "created_at"],
        filters=[
            *_period_filters("created_at", resolved, timestamp=True),
            *_filters_for_accounts("from_account_id", request.account_ids),
        ],
        order_by=[OrderBy(column="created_at", direction=OrderDirection.DESC)],
    )
    orders, _ = await _select(
        database,
        request.scope,
        "payment_orders",
        [
            "id",
            "from_account_id",
            "beneficiary_id",
            "target_account_id",
            "debt_id",
            "kind",
            "amount",
            "fee",
            "currency",
            "requested_date",
            "status",
            "created_at",
        ],
        filters=[
            *_period_filters("created_at", resolved, timestamp=True),
            *_filters_for_accounts("from_account_id", request.account_ids),
        ],
        order_by=[OrderBy(column="created_at", direction=OrderDirection.DESC)],
    )
    items = [{"activity_type": "transfer", **row, "currency": None} for row in transfers] + [
        {"activity_type": "payment_order", **row} for row in orders
    ]
    if request.kinds:
        items = [
            row
            for row in items
            if row.get("activity_type") in request.kinds or row.get("kind") in request.kinds
        ]
    if request.statuses:
        items = [row for row in items if row.get("status") in request.statuses]
    items.sort(key=lambda row: (str(row.get("created_at") or ""), str(row["id"])), reverse=True)
    offset = _cursor_offset(request.cursor)
    page = items[offset : offset + request.limit]
    return {
        "ok": True,
        "period": resolved,
        "items": page,
        "count": len(page),
        "next_cursor": _next_cursor(offset, len(page), offset + len(page) < len(items)),
        "data_quality": {
            "complete": not bool(transfers),
            "warnings": [
                "Legacy transfers have no currency field. / "
                "Las transferencias heredadas no tienen moneda."
            ]
            if transfers
            else [],
        },
    }


async def get_beneficiaries_data(
    database: DatabaseClient, request: BeneficiariesRequest
) -> dict[str, Any]:
    filters: list[FilterCondition] = []
    if request.status:
        filters.append(
            FilterCondition(column="status", operator=FilterOperator.EQ, value=request.status)
        )
    if request.query:
        filters.append(
            FilterCondition(
                column="display_name",
                operator=FilterOperator.ILIKE,
                value=f"%{request.query}%",
            )
        )
    offset = _cursor_offset(request.cursor)
    rows, truncated = await _select(
        database,
        request.scope,
        "beneficiaries",
        ["id", "display_name", "bank_name", "last_four", "status"],
        filters=filters,
        order_by=[OrderBy(column="display_name"), OrderBy(column="id")],
        limit=request.limit,
        offset=offset,
    )
    safe_rows = [
        {key: value for key, value in row.items() if key != "last_four"}
        | {"masked_last_four": f"•••• {row['last_four']}"}
        for row in rows
    ]
    return {
        "ok": True,
        "beneficiaries": safe_rows,
        "count": len(safe_rows),
        "next_cursor": _next_cursor(offset, len(rows), truncated),
    }


__all__ = [
    "get_beneficiaries_data",
    "get_payment_activity_data",
    "get_upcoming_payments_data",
]
