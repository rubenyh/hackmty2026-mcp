"""Account and bank-statement financial reads."""

from __future__ import annotations

from typing import Any

from supabase_mcp.database import DatabaseClient
from supabase_mcp.finance_models.accounts import (
    AccountsRequest,
    BankStatementsRequest,
    CreditCardsRequest,
)
from supabase_mcp.models import FilterCondition, FilterOperator, OrderBy, OrderDirection
from supabase_mcp.services.finance._shared import (
    _cursor_offset,
    _filters_for_accounts,
    _next_cursor,
    _owned_accounts,
    _select,
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
            filters=[
                FilterCondition(column="status", operator=FilterOperator.EQ, value=request.status)
            ]
            if request.status
            else [],
        )
        owned_account_ids = {str(account["id"]) for account in accounts}
        for item in card_rows:
            row = dict(item)
            if str(row.get("account_id")) not in owned_account_ids:
                continue
            last_four = row.pop("last_four", None)
            cards.append(
                {
                    **row,
                    "masked_last_four": f"•••• {last_four}" if last_four else None,
                }
            )
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


async def get_credit_cards_data(
    database: DatabaseClient, request: CreditCardsRequest
) -> dict[str, Any]:
    """Return a bounded, masked projection for credit-card presentation."""

    account_result = await get_accounts_data(
        database,
        AccountsRequest(
            scope=request.scope,
            account_ids=request.account_ids,
            account_type="credit",
            include_cards=True,
            include_credit_terms=True,
            status=request.status,
        ),
    )
    cards: list[dict[str, Any]] = []
    for account in account_result["accounts"]:
        terms = account.get("credit_terms")
        if not isinstance(terms, dict):
            continue
        for card in account.get("cards", []):
            if card.get("card_type") != "credit":
                continue
            cards.append(
                {
                    **card,
                    "account_id": str(account["id"]),
                    "currency": account.get("currency"),
                    "available_credit": account.get("available_balance"),
                    "credit_terms": terms,
                }
            )
    cards.sort(key=lambda card: (card.get("status") != "active", str(card.get("id"))))
    return {"ok": True, "cards": cards, "count": len(cards)}


async def get_bank_statements_data(
    database: DatabaseClient, request: BankStatementsRequest
) -> dict[str, Any]:
    await _owned_accounts(database, request.scope, request.account_ids)
    filters = [*_filters_for_accounts("account_id", request.account_ids)]
    if request.period_start:
        filters.append(
            FilterCondition(
                column="period_end",
                operator=FilterOperator.GTE,
                value=request.period_start.isoformat(),
            )
        )
    if request.period_end:
        filters.append(
            FilterCondition(
                column="period_start",
                operator=FilterOperator.LTE,
                value=request.period_end.isoformat(),
            )
        )
    if request.document_status:
        filters.append(
            FilterCondition(
                column="document_status",
                operator=FilterOperator.EQ,
                value=request.document_status,
            )
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


__all__ = ["get_accounts_data", "get_bank_statements_data", "get_credit_cards_data"]
