"""Execution, error-taxonomy, logging, and transport tests for financial tools."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.tools import ToolResult
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import OperationalError, ProgrammingError, TimeoutError

from supabase_mcp.config import Settings
from supabase_mcp.database import DatabaseClient
from supabase_mcp.errors import InvalidSelectionError, PublicErrorCode
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
from supabase_mcp.models import SelectRequest
from supabase_mcp.server import mcp
from supabase_mcp.services.finance.expenses import get_transaction_disputes_data
from supabase_mcp.tools.finance import (
    FINANCIAL_REQUEST_MODELS,
    FINANCIAL_TOOLS,
    analyze_spending,
    compare_debt_scenarios,
    get_accounts,
    get_bank_statements,
    get_beneficiaries,
    get_budget_progress,
    get_cash_flow,
    get_debt_overview,
    get_financial_alerts,
    get_financial_overview,
    get_payment_activity,
    get_savings_progress,
    get_transaction_disputes,
    get_transactions,
    get_upcoming_payments,
)
from supabase_mcp.tools.finance._shared import _run

USER_A = "11111111-1111-1111-1111-111111111111"
USER_B = "22222222-2222-2222-2222-222222222222"
DEBT_ID = "33333333-3333-3333-3333-333333333333"
ToolCallable = Callable[[BaseModel, Any], Awaitable[ToolResult]]


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "SUPABASE_DATABASE_URL": "postgresql://reader:placeholder@localhost/postgres",
            "MCP_ALLOWED_TABLES": "",
        }
    )


class EmptyDomainDatabase(DatabaseClient):
    """Read-only infrastructure fake that exercises every real domain service."""

    def __init__(self) -> None:
        super().__init__(_settings())
        self.requests: list[SelectRequest] = []

    async def select_domain_rows(
        self, request: SelectRequest
    ) -> tuple[list[dict[str, Any]], int, bool]:
        self.requests.append(request)
        if request.table == "debts" and request.columns == ["id"]:
            return [{"id": DEBT_ID}], request.limit or 1, False
        return [], request.limit or self.settings.default_limit, False


class ScopeFailureDatabase(DatabaseClient):
    def __init__(self) -> None:
        super().__init__(_settings())

    async def select_domain_rows(
        self, request: SelectRequest
    ) -> tuple[list[dict[str, Any]], int, bool]:
        del request
        raise InvalidSelectionError("unknown_user_id", "The selected user is not configured.")


def _context(database: DatabaseClient, correlation_id: str = "test-correlation") -> Any:
    return SimpleNamespace(
        lifespan_context={"database": database},
        request_context=None,
        origin_request_id=correlation_id,
    )


TOOL_CASES: list[tuple[ToolCallable, BaseModel]] = [
    (get_financial_overview, FinancialOverviewRequest(scope={"user_id": USER_A})),
    (get_accounts, AccountsRequest(scope={"user_id": USER_A})),
    (get_transactions, TransactionsRequest(scope={"user_id": USER_A})),
    (analyze_spending, SpendingAnalysisRequest(scope={"user_id": USER_A})),
    (get_cash_flow, CashFlowRequest(scope={"user_id": USER_A})),
    (get_budget_progress, BudgetProgressRequest(scope={"user_id": USER_A})),
    (get_savings_progress, SavingsProgressRequest(scope={"user_id": USER_A})),
    (get_debt_overview, DebtOverviewRequest(scope={"user_id": USER_A})),
    (get_upcoming_payments, UpcomingPaymentsRequest(scope={"user_id": USER_A})),
    (get_financial_alerts, FinancialAlertsRequest(scope={"user_id": USER_A})),
    (get_bank_statements, BankStatementsRequest(scope={"user_id": USER_A})),
    (get_payment_activity, PaymentActivityRequest(scope={"user_id": USER_A})),
    (get_beneficiaries, BeneficiariesRequest(scope={"user_id": USER_A})),
    (get_transaction_disputes, TransactionDisputesRequest(scope={"user_id": USER_A})),
    (
        compare_debt_scenarios,
        CompareDebtScenariosRequest(scope={"user_id": USER_A}, debt_id=DEBT_ID),
    ),
]


def test_financial_request_model_registry_matches_the_registration_tuple() -> None:
    assert set(FINANCIAL_REQUEST_MODELS) == {tool.__name__ for tool in FINANCIAL_TOOLS}


def _case_id(value: object) -> str:
    return value.__name__ if callable(value) else "tool_request"


@pytest.mark.parametrize(("tool", "tool_request"), TOOL_CASES, ids=_case_id)
@pytest.mark.asyncio
async def test_each_financial_tool_has_a_successful_empty_result(
    tool: ToolCallable, tool_request: BaseModel
) -> None:
    result = await tool(tool_request, _context(EmptyDomainDatabase()))

    assert result.is_error is False
    assert result.structured_content["ok"] is True


@pytest.mark.parametrize(("tool", "tool_request"), TOOL_CASES, ids=_case_id)
@pytest.mark.asyncio
async def test_each_financial_tool_has_a_controlled_scope_failure(
    tool: ToolCallable, tool_request: BaseModel
) -> None:
    result = await tool(tool_request, _context(ScopeFailureDatabase()))

    assert result.is_error is True
    error = result.structured_content["error"]
    assert error["code"] == PublicErrorCode.USER_SCOPE_ERROR
    assert error["details"]["layer"] == "user_scope"
    assert error["tool"] == tool.__name__


@pytest.mark.parametrize("model", [TransactionsRequest, SpendingAnalysisRequest, CashFlowRequest])
def test_every_literal_period_subtype_requires_complete_ordered_custom_dates(
    model: type[BaseModel],
) -> None:
    with pytest.raises(ValidationError) as missing:
        model.model_validate({"scope": {"user_id": USER_A}, "period": "custom"})
    assert missing.value.errors()[0]["type"] == "invalid_date_range"

    with pytest.raises(ValidationError) as inverted:
        model.model_validate(
            {
                "scope": {"user_id": USER_A},
                "period": "custom",
                "start_date": "2026-09-12",
                "end_date": "2026-09-01",
            }
        )
    assert inverted.value.errors()[0]["type"] == "invalid_date_range"


def test_model_arguments_cannot_add_or_replace_effective_identity() -> None:
    with pytest.raises(ValidationError):
        TransactionsRequest.model_validate({"scope": {"user_id": USER_A}, "user_id": USER_B})


@pytest.mark.asyncio
async def test_dispute_period_is_applied_and_empty_results_do_not_fetch_all_transactions() -> None:
    database = EmptyDomainDatabase()
    result = await get_transaction_disputes_data(
        database,
        TransactionDisputesRequest(scope={"user_id": USER_A}, period="today"),
    )

    dispute_request = next(
        item for item in database.requests if item.table == "transaction_disputes"
    )
    assert [item.column for item in dispute_request.filters].count("created_at") == 2
    assert not any(item.table == "transactions" for item in database.requests)
    assert result == {"ok": True, "disputes": [], "count": 0, "next_cursor": None}


class _DriverFailure(Exception):
    def __init__(self, sqlstate: str, message: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("failure", "expected_code", "retryable"),
    [
        (TimeoutError("secret timeout"), PublicErrorCode.DATABASE_TIMEOUT, True),
        (
            OperationalError("SELECT secret", {"token": "secret"}, OSError("secret DSN")),
            PublicErrorCode.DATABASE_UNAVAILABLE,
            True,
        ),
        (
            ProgrammingError(
                "SELECT secret",
                {"password": "secret"},
                _DriverFailure("42501", "permission secret"),
            ),
            PublicErrorCode.DATABASE_PERMISSION_ERROR,
            False,
        ),
        (
            ProgrammingError(
                "SELECT secret", {"password": "secret"}, _DriverFailure("22000", "bad data")
            ),
            PublicErrorCode.DATABASE_QUERY_ERROR,
            False,
        ),
        (KeyError("secret_column"), PublicErrorCode.DATA_MAPPING_ERROR, False),
    ],
)
@pytest.mark.asyncio
async def test_database_and_mapping_failures_are_distinct_sanitized_and_logged(
    failure: Exception,
    expected_code: PublicErrorCode,
    retryable: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fail(_database: Any, _request: AccountsRequest) -> dict[str, Any]:
        raise failure

    caplog.set_level(logging.INFO, logger="supabase_mcp.tools.finance._shared")
    result = await _run(
        "get_accounts",
        AccountsRequest(scope={"user_id": USER_A}),
        _context(EmptyDomainDatabase(), "error-correlation"),
        fail,
    )

    payload = result.structured_content
    serialized = json.dumps(payload)
    assert result.is_error is True
    assert payload["error"]["code"] == expected_code
    assert payload["error"]["retryable"] is retryable
    assert payload["error"]["correlation_id"] == "error-correlation"
    assert "secret" not in serialized.lower()
    assert "select secret" not in serialized.lower()
    failure_record = next(record for record in caplog.records if record.levelno == logging.ERROR)
    assert failure_record.correlation_id == "error-correlation"
    assert failure_record.exception_type == type(failure).__name__
    assert failure_record.exc_info is not None
    assert "secret" not in caplog.text.lower()
    assert "select secret" not in caplog.text.lower()


@pytest.mark.asyncio
async def test_validation_and_cursor_errors_survive_mcp_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SUPABASE_DATABASE_URL",
        "postgresql://reader:password@localhost/postgres?sslmode=require",
    )
    monkeypatch.setenv("MCP_ALLOWED_TABLES", "")
    async with Client(mcp) as client:
        invalid_dates = await client.call_tool(
            "get_transactions",
            {"request": {"scope": {"user_id": USER_A}, "period": "custom"}},
            raise_on_error=False,
            meta={"correlation_id": "validation-transport"},
        )
        invalid_cursor = await client.call_tool(
            "get_beneficiaries",
            {"request": {"scope": {"user_id": USER_A}, "cursor": "not-base64!"}},
            raise_on_error=False,
            meta={"correlation_id": "cursor-transport"},
        )

    assert invalid_dates.structured_content["error"]["code"] == "INVALID_DATE_RANGE"
    assert invalid_dates.structured_content["error"]["correlation_id"] == "validation-transport"
    assert invalid_cursor.structured_content["error"]["code"] == "INVALID_CURSOR"
    assert invalid_cursor.structured_content["error"]["correlation_id"] == "cursor-transport"
    assert json.loads(invalid_cursor.content[0].text) == invalid_cursor.structured_content
