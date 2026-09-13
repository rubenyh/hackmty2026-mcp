"""Cash-flow financial reads."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any
from uuid import UUID

from supabase_mcp.database import DatabaseClient
from supabase_mcp.finance_models.cash_flow import CashFlowRequest
from supabase_mcp.models import OrderBy
from supabase_mcp.services.finance._shared import (
    _currency_map,
    _filters_for_accounts,
    _iso_date,
    _money,
    _owned_accounts,
    _period_filters,
    _select,
    resolve_period,
)


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
    series: list[dict[str, Any]] = [
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


__all__ = ["get_cash_flow_data"]
