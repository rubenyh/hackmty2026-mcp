"""Offline contract tests for the fifteen financial domain tools."""

from __future__ import annotations

from datetime import date

import pytest
from fastmcp import Client
from pydantic import ValidationError

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
    TransactionDisputesRequest,
    TransactionsRequest,
    UpcomingPaymentsRequest,
)
from supabase_mcp.server import mcp
from supabase_mcp.services.finance import resolve_period
from supabase_mcp.tools.finance import FINANCIAL_TOOLS

USER_A = "11111111-1111-1111-1111-111111111111"
FINANCIAL_NAMES = {
    "get_financial_overview",
    "get_accounts",
    "get_transactions",
    "analyze_spending",
    "get_cash_flow",
    "get_budget_progress",
    "get_savings_progress",
    "get_debt_overview",
    "get_upcoming_payments",
    "get_financial_alerts",
    "get_bank_statements",
    "get_payment_activity",
    "get_beneficiaries",
    "get_transaction_disputes",
    "compare_debt_scenarios",
}


@pytest.mark.asyncio
async def test_all_fifteen_tools_are_registered_with_bilingual_discovery_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SUPABASE_DATABASE_URL",
        "postgresql://reader:password@localhost/postgres?sslmode=require",
    )
    monkeypatch.setenv("MCP_ALLOWED_TABLES", "")
    async with Client(mcp) as client:
        listed = {tool.name: tool for tool in await client.list_tools()}
    assert {tool.__name__ for tool in FINANCIAL_TOOLS} == FINANCIAL_NAMES
    assert FINANCIAL_NAMES <= listed.keys()
    for name in FINANCIAL_NAMES:
        description = listed[name].description or ""
        assert "/" in description
        assert "request" in listed[name].input_schema["properties"]
        request_schema = listed[name].input_schema["properties"]["request"]
        assert "scope" in request_schema["properties"]
        assert listed[name].annotations is not None
        assert listed[name].annotations.read_only_hint is True


@pytest.mark.parametrize(
    "model",
    [
        FinancialOverviewRequest,
        AccountsRequest,
        TransactionsRequest,
        SpendingAnalysisRequest,
        CashFlowRequest,
        BudgetProgressRequest,
        SavingsProgressRequest,
        DebtOverviewRequest,
        UpcomingPaymentsRequest,
        FinancialAlertsRequest,
        BankStatementsRequest,
        PaymentActivityRequest,
        BeneficiariesRequest,
        TransactionDisputesRequest,
    ],
)
def test_each_request_rejects_unknown_fields(model: type[object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"scope": {"user_id": USER_A}, "unexpected": True})  # type: ignore[attr-defined]


def test_compare_request_requires_a_debt_and_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CompareDebtScenariosRequest.model_validate(
            {"scope": {"user_id": USER_A}, "unexpected": True}
        )


def test_period_resolution_is_centralized_inclusive_and_timezone_aware() -> None:
    assert resolve_period(
        "previous_month", timezone_name="America/Monterrey", today=date(2026, 9, 12)
    ) == {
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "end_inclusive": True,
        "timezone": "America/Monterrey",
    }
    assert resolve_period(
        "last_6_months", timezone_name="America/Monterrey", today=date(2026, 9, 12)
    )["start_date"] == "2026-04-01"


def test_custom_period_and_limits_are_strict() -> None:
    with pytest.raises(ValidationError):
        TransactionsRequest.model_validate(
            {"scope": {"user_id": USER_A}, "period": "custom"}
        )
    with pytest.raises(ValidationError):
        TransactionsRequest.model_validate(
            {"scope": {"user_id": USER_A}, "limit": 101}
        )
    request = TransactionsRequest.model_validate(
        {
            "scope": {"user_id": USER_A},
            "period": "custom",
            "start_date": "2026-09-01",
            "end_date": "2026-09-12",
        }
    )
    assert request.start_date == date(2026, 9, 1)
