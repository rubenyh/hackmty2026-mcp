"""Shared financial query, ownership, period, and pagination helpers."""

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
from supabase_mcp.finance_models import TimePeriod
from supabase_mcp.models import FilterCondition, FilterOperator, OrderBy, SelectRequest, UserScope

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
            FilterCondition(column=column, operator=FilterOperator.GTE, value=start_value),
            FilterCondition(column=column, operator=FilterOperator.LT, value=end_value),
        ]
    return [
        FilterCondition(column=column, operator=FilterOperator.GTE, value=start.isoformat()),
        FilterCondition(column=column, operator=FilterOperator.LTE, value=end.isoformat()),
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
        [
            FilterCondition(
                column="id",
                operator=FilterOperator.IN,
                value=[_uuid_text(v) for v in account_ids],
            )
        ]
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
        filters=[
            FilterCondition(
                column=column,
                operator=FilterOperator.IN,
                value=[str(v) for v in values],
            )
        ],
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
        [
            FilterCondition(
                column=column,
                operator=FilterOperator.IN,
                value=[str(v) for v in account_ids],
            )
        ]
        if account_ids
        else []
    )
