"""Business-owned, user-scoped financial reads over the reflected database boundary."""

from __future__ import annotations

import base64
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from supabase_mcp.database import DatabaseClient
from supabase_mcp.errors import SafeMCPError
from supabase_mcp.finance_models import (
    AccountsRequest,
    BankStatementsRequest,
    BeneficiariesRequest,
    BudgetProgressRequest,
    CashFlowRequest,
    CompareDebtScenariosRequest,
    DebtOverviewRequest,
    FinancialAlertsRequest,
    FinancialOverviewRequest,
    PaymentActivityRequest,
    SavingsProgressRequest,
    SpendingAnalysisRequest,
    TimePeriod,
    TransactionDisputesRequest,
    TransactionsRequest,
    UpcomingPaymentsRequest,
)
from supabase_mcp.models import FilterCondition, OrderBy, OrderDirection, SelectRequest, UserScope

PUBLIC_SCHEMA = "public"
MAX_DOMAIN_ROWS = 500


def _money(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SafeMCPError("invalid_data", "A stored financial amount is invalid.") from exc


def _uuid_text(value: UUID | str) -> str:
    return str(value)


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, str):
        return value[:10]
    return str(value)


def _cursor_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8")
        payload = json.loads(raw)
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeMCPError("invalid_cursor", "The pagination cursor is invalid.") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise SafeMCPError("invalid_cursor", "The pagination cursor is invalid.")
    offset = payload.get("offset")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or offset > 1_000_000:
        raise SafeMCPError("invalid_cursor", "The pagination cursor is invalid.")
    return offset


def _next_cursor(offset: int, count: int, truncated: bool) -> str | None:
    if not truncated:
        return None
    raw = json.dumps({"v": 1, "offset": offset + count}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def resolve_period(
    period: TimePeriod | str,
    *,
    timezone_name: str,
    start_date: date | None = None,
    end_date: date | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Resolve one canonical period; end_date is inclusive for public contracts."""
    current = today or datetime.now(ZoneInfo(timezone_name)).date()
    value = TimePeriod(period)
    if value is TimePeriod.CUSTOM:
        if start_date is None or end_date is None or end_date < start_date:
            raise SafeMCPError("invalid_period", "The custom date range is invalid.")
        start, end = start_date, end_date
    elif value is TimePeriod.TODAY:
        start = end = current
    elif value is TimePeriod.CURRENT_WEEK:
        start, end = current - timedelta(days=current.weekday()), current
    elif value is TimePeriod.CURRENT_MONTH:
        start, end = current.replace(day=1), current
    elif value is TimePeriod.PREVIOUS_MONTH:
        end = current.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    elif value is TimePeriod.LAST_30_DAYS:
        start, end = current - timedelta(days=29), current
    elif value is TimePeriod.LAST_90_DAYS:
        start, end = current - timedelta(days=89), current
    elif value in {TimePeriod.LAST_3_MONTHS, TimePeriod.LAST_6_MONTHS, TimePeriod.LAST_12_MONTHS}:
        months = {
            TimePeriod.LAST_3_MONTHS: 3,
            TimePeriod.LAST_6_MONTHS: 6,
            TimePeriod.LAST_12_MONTHS: 12,
        }[value]
        first = current.replace(day=1)
        year = first.year + (first.month - months) // 12
        month = (first.month - months) % 12 + 1
        start, end = date(year, month, 1), current
    else:
        start, end = current.replace(month=1, day=1), current
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "end_inclusive": True,
        "timezone": timezone_name,
    }


def _period_filters(
    column: str, resolved: Mapping[str, Any], *, timestamp: bool
) -> list[FilterCondition]:
    start = date.fromisoformat(str(resolved["start_date"]))
    end = date.fromisoformat(str(resolved["end_date"]))
    if timestamp:
        zone = ZoneInfo(str(resolved["timezone"]))
        start_value = datetime.combine(start, time.min, zone).astimezone(UTC).isoformat()
        end_value = (
            datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(UTC).isoformat()
        )
        return [
            FilterCondition(column=column, operator="gte", value=start_value),
            FilterCondition(column=column, operator="lt", value=end_value),
        ]
    return [
        FilterCondition(column=column, operator="gte", value=start.isoformat()),
        FilterCondition(column=column, operator="lte", value=end.isoformat()),
    ]


async def _select(
    database: DatabaseClient,
    scope: UserScope,
    table: str,
    columns: list[str],
    *,
    filters: Sequence[FilterCondition] = (),
    order_by: Sequence[OrderBy] = (),
    limit: int = MAX_DOMAIN_ROWS,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], bool]:
    effective_limit = min(limit, database.settings.max_limit, MAX_DOMAIN_ROWS)
    rows, _limit, truncated = await database.select_domain_rows(
        SelectRequest(
            schema=PUBLIC_SCHEMA,
            table=table,
            scope=scope,
            columns=columns,
            filters=list(filters),
            order_by=list(order_by),
            limit=effective_limit,
            offset=offset,
        )
    )
    return rows, truncated


async def _owned_accounts(
    database: DatabaseClient, scope: UserScope, account_ids: Sequence[UUID] = ()
) -> list[dict[str, Any]]:
    filters = (
        [FilterCondition(column="id", operator="in", value=[_uuid_text(v) for v in account_ids])]
        if account_ids
        else []
    )
    rows, _ = await _select(
        database,
        scope,
        "accounts",
        ["id", "account_type", "currency", "available_balance"],
        filters=filters,
        limit=max(len(account_ids), 100),
    )
    if account_ids and {str(row["id"]) for row in rows} != {
        _uuid_text(value) for value in account_ids
    }:
        raise SafeMCPError("resource_not_found", "A requested resource was not found.")
    return rows


async def _require_owned_ids(
    database: DatabaseClient,
    scope: UserScope,
    table: str,
    column: str,
    values: Sequence[UUID],
) -> None:
    if not values:
        return
    rows, _ = await _select(
        database,
        scope,
        table,
        [column],
        filters=[FilterCondition(column=column, operator="in", value=[str(v) for v in values])],
        limit=len(values),
    )
    if {str(row[column]) for row in rows} != {str(value) for value in values}:
        raise SafeMCPError("resource_not_found", "A requested resource was not found.")


def _currency_map(accounts: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    return {str(row["id"]): str(row["currency"]) for row in accounts}


def _sum_by_currency(
    rows: Iterable[Mapping[str, Any]], currency_key: str, amount_key: str
) -> list[dict[str, Any]]:
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        currency = row.get(currency_key)
        if isinstance(currency, str):
            totals[currency] += _money(row.get(amount_key))
    return [{"currency": key, "total": value} for key, value in sorted(totals.items())]


def _filters_for_accounts(column: str, account_ids: Sequence[UUID]) -> list[FilterCondition]:
    return (
        [FilterCondition(column=column, operator="in", value=[str(v) for v in account_ids])]
        if account_ids
        else []
    )


async def get_accounts_data(database: DatabaseClient, request: AccountsRequest) -> dict[str, Any]:
    accounts = await _owned_accounts(database, request.scope, request.account_ids)
    if request.account_type:
        accounts = [row for row in accounts if row.get("account_type") == request.account_type]
    details, _ = await _select(
        database,
        request.scope,
        "account_details",
        ["account_id", "display_name", "bank_name", "last_four"],
    )
    details_by_account = {str(row["account_id"]): row for row in details}
    cards: list[dict[str, Any]] = []
    if request.include_cards:
        card_rows, _ = await _select(
            database,
            request.scope,
            "cards",
            [
                "id",
                "account_id",
                "display_name",
                "card_type",
                "network",
                "last_four",
                "status",
                "expires_month",
                "expires_year",
            ],
            filters=[FilterCondition(column="status", operator="eq", value=request.status)]
            if request.status
            else [],
        )
        cards = [
            {**row, "masked_last_four": f"•••• {row.pop('last_four')}"}
            for row in (dict(item) for item in card_rows)
            if str(row.get("account_id")) in {str(account["id"]) for account in accounts}
        ]
    terms_by_account: dict[str, dict[str, Any]] = {}
    if request.include_credit_terms:
        term_rows, _ = await _select(
            database,
            request.scope,
            "credit_card_terms",
            [
                "account_id",
                "currency",
                "credit_limit",
                "current_debt",
                "statement_balance",
                "minimum_payment",
                "interest_free_payment",
                "annual_interest_rate",
                "cat_percentage",
                "cutoff_date",
                "due_date",
                "as_of",
            ],
            order_by=[OrderBy(column="as_of", direction=OrderDirection.DESC)],
        )
        for row in term_rows:
            terms_by_account.setdefault(str(row["account_id"]), row)
    result = []
    for account in accounts:
        account_id = str(account["id"])
        detail = details_by_account.get(account_id, {})
        last_four = detail.get("last_four")
        result.append(
            {
                **account,
                "display_name": detail.get("display_name")
                or str(account.get("account_type", "account")).replace("_", " ").title(),
                "bank_name": detail.get("bank_name"),
                "masked_last_four": f"•••• {last_four}" if last_four else None,
                "cards": [card for card in cards if str(card.get("account_id")) == account_id],
                "credit_terms": terms_by_account.get(account_id),
            }
        )
    return {"ok": True, "accounts": result, "count": len(result)}


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
                operator="eq",
                value="credit" if request.direction == "income" else "debit",
            )
        )
    if request.categories:
        filters.append(FilterCondition(column="category", operator="in", value=request.categories))
    if request.merchant_query:
        filters.append(
            FilterCondition(
                column="merchant", operator="ilike", value=f"%{request.merchant_query}%"
            )
        )
    if request.min_amount is not None:
        filters.append(
            FilterCondition(column="amount", operator="gte", value=str(request.min_amount))
        )
    if request.max_amount is not None:
        filters.append(
            FilterCondition(column="amount", operator="lte", value=str(request.max_amount))
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
            FilterCondition(column="direction", operator="eq", value="debit"),
        ]
        if request.categories:
            filters.append(
                FilterCondition(column="category", operator="in", value=request.categories)
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


async def get_cash_flow_data(database: DatabaseClient, request: CashFlowRequest) -> dict[str, Any]:
    accounts = await _owned_accounts(database, request.scope, request.account_ids)
    account_ids = request.account_ids or [UUID(str(row["id"])) for row in accounts]
    resolved = resolve_period(
        request.period,
        timezone_name=database.settings.timezone,
        start_date=request.start_date,
        end_date=request.end_date,
    )
    rows, _ = await _select(
        database,
        request.scope,
        "monthly_cash_flow",
        ["account_id", "month", "income", "expenses", "net"],
        filters=[
            *_period_filters("month", resolved, timestamp=False),
            *_filters_for_accounts("account_id", account_ids),
        ],
        order_by=[OrderBy(column="month"), OrderBy(column="account_id")],
    )
    currencies = _currency_map(accounts)
    series_totals: defaultdict[tuple[str, str], dict[str, Decimal]] = defaultdict(
        lambda: {"income": Decimal(), "expenses": Decimal(), "net": Decimal()}
    )
    for row in rows:
        key = (_iso_date(row["month"]) or "", currencies[str(row["account_id"])])
        for field in ("income", "expenses", "net"):
            series_totals[key][field] += _money(row[field])
    series = [
        {"month": month, "currency": currency, **values}
        for (month, currency), values in sorted(series_totals.items())
    ]
    totals: defaultdict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"income": Decimal(), "expenses": Decimal(), "net": Decimal()}
    )
    for item in series:
        for field in ("income", "expenses", "net"):
            totals[item["currency"]][field] += item[field]
    return {
        "ok": True,
        "period": resolved,
        "totals_by_currency": [
            {"currency": currency, **values} for currency, values in sorted(totals.items())
        ],
        "series": series,
    }


async def get_budget_progress_data(
    database: DatabaseClient, request: BudgetProgressRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    await _require_owned_ids(database, request.scope, "budgets", "id", request.budget_ids)
    filters = [*_filters_for_accounts("account_id", request.account_ids)]
    if request.budget_ids:
        filters.append(
            FilterCondition(column="id", operator="in", value=[str(v) for v in request.budget_ids])
        )
    if request.category:
        filters.append(FilterCondition(column="category", operator="eq", value=request.category))
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


async def get_savings_progress_data(
    database: DatabaseClient, request: SavingsProgressRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    await _require_owned_ids(database, request.scope, "savings_goals", "id", request.goal_ids)
    filters = [*_filters_for_accounts("account_id", request.account_ids)]
    if request.goal_ids:
        filters.append(
            FilterCondition(column="id", operator="in", value=[str(v) for v in request.goal_ids])
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
                filters=[FilterCondition(column="goal_id", operator="in", value=selected_ids)],
                order_by=[OrderBy(column="contributed_at", direction=OrderDirection.DESC)],
                limit=request.contributions_limit,
            )
    return {"ok": True, "goals": goals, "contributions": contributions, "count": len(goals)}


async def get_debt_overview_data(
    database: DatabaseClient, request: DebtOverviewRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    await _require_owned_ids(database, request.scope, "debts", "id", request.debt_ids)
    filters = [*_filters_for_accounts("account_id", request.account_ids)]
    if request.debt_ids:
        filters.append(
            FilterCondition(column="id", operator="in", value=[str(v) for v in request.debt_ids])
        )
    rows, _ = await _select(
        database,
        request.scope,
        "debts",
        [
            "id",
            "account_id",
            "name",
            "debt_type",
            "currency",
            "outstanding_principal",
            "annual_interest_rate",
            "monthly_payment",
            "next_due_date",
            "status",
        ],
        filters=filters,
        order_by=[OrderBy(column="next_due_date")],
    )
    debts = [row for row in rows if request.status == "all" or row.get("status") == request.status]
    scenarios: list[dict[str, Any]] = []
    if request.include_scenarios:
        debt_ids = [str(row["id"]) for row in debts]
        if debt_ids:
            scenarios, _ = await _select(
                database,
                request.scope,
                "debt_scenarios",
                [
                    "id",
                    "debt_id",
                    "name",
                    "monthly_payment",
                    "extra_monthly_payment",
                    "estimated_months",
                    "total_interest",
                    "total_paid",
                    "assumptions",
                    "calculated_at",
                ],
                filters=[FilterCondition(column="debt_id", operator="in", value=debt_ids)],
            )
    cards: list[dict[str, Any]] = []
    if request.include_credit_cards:
        terms, _ = await _select(
            database,
            request.scope,
            "credit_card_terms",
            [
                "id",
                "account_id",
                "currency",
                "credit_limit",
                "current_debt",
                "statement_balance",
                "minimum_payment",
                "interest_free_payment",
                "annual_interest_rate",
                "cutoff_date",
                "due_date",
                "as_of",
            ],
            filters=_filters_for_accounts("account_id", request.account_ids),
            order_by=[OrderBy(column="as_of", direction=OrderDirection.DESC)],
        )
        seen: set[str] = set()
        for row in terms:
            account_id = str(row["account_id"])
            if account_id in seen:
                continue
            seen.add(account_id)
            limit = _money(row["credit_limit"])
            cards.append(
                {
                    **row,
                    "utilization_percentage": (_money(row["current_debt"]) / limit * Decimal("100"))
                    if limit
                    else None,
                }
            )
    totals: defaultdict[str, dict[str, Decimal]] = defaultdict(
        lambda: {
            "outstanding_principal": Decimal(),
            "monthly_payment": Decimal(),
            "credit_card_debt": Decimal(),
        }
    )
    for row in debts:
        totals[str(row["currency"])]["outstanding_principal"] += _money(
            row["outstanding_principal"]
        )
        totals[str(row["currency"])]["monthly_payment"] += _money(row["monthly_payment"])
    for row in cards:
        totals[str(row["currency"])]["credit_card_debt"] += _money(row["current_debt"])
    return {
        "ok": True,
        "totals_by_currency": [
            {"currency": currency, **values} for currency, values in sorted(totals.items())
        ],
        "debts": debts,
        "credit_cards": cards,
        "scenarios": scenarios,
        "advisory": (
            "Minimum payment is a contractual amount, not a recommendation. / "
            "El pago mínimo es contractual, no una recomendación."
        ),
    }


async def get_upcoming_payments_data(
    database: DatabaseClient, request: UpcomingPaymentsRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    today = datetime.now(ZoneInfo(database.settings.timezone)).date()
    through = today + timedelta(days=request.days_ahead)
    date_filters = [
        FilterCondition(column="scheduled_date", operator="gte", value=today.isoformat()),
        FilterCondition(column="scheduled_date", operator="lte", value=through.isoformat()),
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
            FilterCondition(column="next_charge_date", operator="gte", value=today.isoformat()),
            FilterCondition(column="next_charge_date", operator="lte", value=through.isoformat()),
        ],
    )
    debts, _ = await _select(
        database,
        request.scope,
        "debts",
        ["id", "account_id", "name", "monthly_payment", "currency", "next_due_date", "status"],
        filters=[
            FilterCondition(column="next_due_date", operator="gte", value=today.isoformat()),
            FilterCondition(column="next_due_date", operator="lte", value=through.isoformat()),
            *_filters_for_accounts("account_id", request.account_ids),
        ],
    )
    terms, _ = await _select(
        database,
        request.scope,
        "credit_card_terms",
        ["id", "account_id", "interest_free_payment", "currency", "due_date", "as_of"],
        filters=[
            FilterCondition(column="due_date", operator="gte", value=today.isoformat()),
            FilterCondition(column="due_date", operator="lte", value=through.isoformat()),
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
            FilterCondition(column="requested_date", operator="gte", value=today.isoformat()),
            FilterCondition(column="requested_date", operator="lte", value=through.isoformat()),
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


async def get_financial_alerts_data(
    database: DatabaseClient, request: FinancialAlertsRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    await _require_owned_ids(database, request.scope, "budgets", "id", request.budget_ids)
    filters = [*_filters_for_accounts("account_id", request.account_ids)]
    if request.status != "all":
        filters.append(FilterCondition(column="status", operator="eq", value=request.status))
    if request.kinds:
        filters.append(FilterCondition(column="kind", operator="in", value=request.kinds))
    if request.budget_ids:
        filters.append(
            FilterCondition(
                column="budget_id", operator="in", value=[str(v) for v in request.budget_ids]
            )
        )
    if request.due_within_days is not None:
        today = datetime.now(ZoneInfo(database.settings.timezone)).date()
        filters.extend(
            [
                FilterCondition(column="due_date", operator="gte", value=today.isoformat()),
                FilterCondition(
                    column="due_date",
                    operator="lte",
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


async def get_bank_statements_data(
    database: DatabaseClient, request: BankStatementsRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    filters = [*_filters_for_accounts("account_id", request.account_ids)]
    if request.period_start:
        filters.append(
            FilterCondition(
                column="period_end", operator="gte", value=request.period_start.isoformat()
            )
        )
    if request.period_end:
        filters.append(
            FilterCondition(
                column="period_start", operator="lte", value=request.period_end.isoformat()
            )
        )
    if request.document_status:
        filters.append(
            FilterCondition(column="document_status", operator="eq", value=request.document_status)
        )
    offset = _cursor_offset(request.cursor)
    rows, truncated = await _select(
        database,
        request.scope,
        "bank_statements",
        [
            "id",
            "account_id",
            "period_start",
            "period_end",
            "currency",
            "opening_balance",
            "total_income",
            "total_expenses",
            "closing_balance",
            "document_status",
        ],
        filters=filters,
        order_by=[
            OrderBy(column="period_start", direction=OrderDirection.DESC),
            OrderBy(column="id", direction=OrderDirection.DESC),
        ],
        limit=request.limit,
        offset=offset,
    )
    return {
        "ok": True,
        "statements": rows,
        "count": len(rows),
        "next_cursor": _next_cursor(offset, len(rows), truncated),
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
        filters.append(FilterCondition(column="status", operator="eq", value=request.status))
    if request.query:
        filters.append(
            FilterCondition(column="display_name", operator="ilike", value=f"%{request.query}%")
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


async def get_transaction_disputes_data(
    database: DatabaseClient, request: TransactionDisputesRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    await _require_owned_ids(database, request.scope, "transactions", "id", request.transaction_ids)
    filters = [*_filters_for_accounts("account_id", request.account_ids)]
    if request.statuses:
        filters.append(FilterCondition(column="status", operator="in", value=request.statuses))
    if request.transaction_ids:
        filters.append(
            FilterCondition(
                column="transaction_id",
                operator="in",
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
    transactions, _ = await _select(
        database,
        request.scope,
        "transactions",
        ["id", "account_id", "amount", "direction", "category", "merchant", "occurred_at"],
        filters=[FilterCondition(column="id", operator="in", value=transaction_ids)]
        if transaction_ids
        else [],
    )
    by_id = {str(row["id"]): row for row in transactions}
    results = [{**row, "transaction": by_id.get(str(row["transaction_id"]))} for row in disputes]
    return {
        "ok": True,
        "disputes": results,
        "count": len(results),
        "next_cursor": _next_cursor(offset, len(results), truncated),
    }


async def compare_debt_scenarios_data(
    database: DatabaseClient, request: CompareDebtScenariosRequest
) -> dict[str, Any]:
    await _require_owned_ids(database, request.scope, "debts", "id", [request.debt_id])
    await _require_owned_ids(database, request.scope, "debt_scenarios", "id", request.scenario_ids)
    filters = [FilterCondition(column="debt_id", operator="eq", value=str(request.debt_id))]
    if request.scenario_ids:
        filters.append(
            FilterCondition(
                column="id", operator="in", value=[str(v) for v in request.scenario_ids]
            )
        )
    rows, _ = await _select(
        database,
        request.scope,
        "debt_scenarios",
        [
            "id",
            "debt_id",
            "name",
            "monthly_payment",
            "extra_monthly_payment",
            "estimated_months",
            "total_interest",
            "total_paid",
            "assumptions",
            "calculated_at",
        ],
        filters=filters,
    )
    if request.scenario_ids and len(rows) != len(request.scenario_ids):
        raise SafeMCPError("resource_not_found", "A requested resource was not found.")
    key = {
        "lowest_total_interest": lambda row: (_money(row["total_interest"]), str(row["id"])),
        "lowest_monthly_payment": lambda row: (_money(row["monthly_payment"]), str(row["id"])),
        "fastest_payoff": lambda row: (int(row["estimated_months"]), str(row["id"])),
    }[request.order_by]
    ordered = sorted(rows, key=key)
    baseline = ordered[0] if ordered else None
    scenarios = []
    for row in ordered:
        scenarios.append(
            {
                **row,
                "differences_against_baseline": {
                    "monthly_payment": _money(row["monthly_payment"])
                    - _money(baseline["monthly_payment"]),
                    "estimated_months": int(row["estimated_months"])
                    - int(baseline["estimated_months"]),
                    "total_interest": _money(row["total_interest"])
                    - _money(baseline["total_interest"]),
                    "total_paid": _money(row["total_paid"]) - _money(baseline["total_paid"]),
                }
                if baseline
                else None,
            }
        )
    return {
        "ok": True,
        "debt_id": str(request.debt_id),
        "baseline_scenario_id": str(baseline["id"]) if baseline else None,
        "order_by": request.order_by,
        "scenarios": scenarios,
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


__all__ = [name for name in globals() if name.endswith("_data") or name == "resolve_period"]
