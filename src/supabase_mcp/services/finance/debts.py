"""Debt-overview and scenario-comparison financial reads."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, cast

from supabase_mcp.database import DatabaseClient
from supabase_mcp.errors import SafeMCPError
from supabase_mcp.finance_models.debts import CompareDebtScenariosRequest, DebtOverviewRequest
from supabase_mcp.models import (
    FilterCondition,
    FilterOperator,
    FilterValue,
    OrderBy,
    OrderDirection,
)
from supabase_mcp.services.finance._shared import (
    _filters_for_accounts,
    _money,
    _owned_accounts,
    _require_owned_ids,
    _select,
)


async def get_debt_overview_data(
    database: DatabaseClient, request: DebtOverviewRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    await _require_owned_ids(database, request.scope, "debts", "id", request.debt_ids)
    filters = [*_filters_for_accounts("account_id", request.account_ids)]
    if request.debt_ids:
        filters.append(
            FilterCondition(
                column="id",
                operator=FilterOperator.IN,
                value=[str(v) for v in request.debt_ids],
            )
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
                filters=[
                    FilterCondition(
                        column="debt_id",
                        operator=FilterOperator.IN,
                        value=cast(FilterValue, debt_ids),
                    )
                ],
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


async def compare_debt_scenarios_data(
    database: DatabaseClient, request: CompareDebtScenariosRequest
) -> dict[str, Any]:
    await _require_owned_ids(database, request.scope, "debts", "id", [request.debt_id])
    await _require_owned_ids(database, request.scope, "debt_scenarios", "id", request.scenario_ids)
    filters = [
        FilterCondition(column="debt_id", operator=FilterOperator.EQ, value=str(request.debt_id))
    ]
    if request.scenario_ids:
        filters.append(
            FilterCondition(
                column="id",
                operator=FilterOperator.IN,
                value=[str(v) for v in request.scenario_ids],
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


__all__ = ["compare_debt_scenarios_data", "get_debt_overview_data"]
