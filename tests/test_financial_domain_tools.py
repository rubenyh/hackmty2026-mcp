"""Offline contract tests for the fifteen financial domain tools."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

import pytest
from fastmcp import Client
from hatchling.build import build_wheel
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
FINANCIAL_CONTRACT_HASHES = {
    "analyze_spending": "779367d2aa22dfd0b558a76a397f81c7af3fce80380a9b0558313a797921669d",
    "compare_debt_scenarios": "05f3f2f9cd3373959b783320fb2d290b4418f90d086fa22dc7c12eda62dc560d",
    "get_accounts": "93d62c0d63124056cabcb985bee5143e701730177728f21bd37729ea1980b144",
    "get_bank_statements": "6b854309531c998e8c82be9b109032daa1613c97112133fd98dc6234ba9d8ae8",
    "get_beneficiaries": "1a4a3b28804e5f4d0f5c3943713b1fa65836544a22ff191c717ed8b510c80a22",
    "get_budget_progress": "b2d84a559c88283f706348a4092caea755c7d34d20d29ef65ecbbc8146d0d5ec",
    "get_cash_flow": "f417e417b3ca47ea4a319453f2ea982b2e5557003766ea6907bee4ef521458ad",
    "get_debt_overview": "d1048d8366a34f57b3548c760a13b95bbe46a85d9d58ad5228308eb8d4ed9644",
    "get_financial_alerts": "30f130ed906b039036d8fe539d4c3d363eb9ec34f13f898b4afe9d2e04c9c64c",
    "get_financial_overview": "77a35cd2ccd0f1ad0a673fb06ccdf8d2c32999403d6607bfbda0ce5ada5a669f",
    "get_payment_activity": "b3a3bbe525c06ba36b60fb10aa7f494e9cd678ae02b1d142535e22c85aca2c4e",
    "get_savings_progress": "546915ad46e8273642b1164a40a287721a4bcae02462be988f2aae3674a7f836",
    "get_transaction_disputes": "bb8706218e625b2418dcb16850a906b537c9878bbcc7ef0902261cf62e0d4c01",
    "get_transactions": "9b4d27b0b5d4df3db81d519045f4f523514eb9f2385a7685092f1eb7a23a924c",
    "get_upcoming_payments": "619144bd1b4b3dd25a7a5c6264cc729162051369d66902fa0304dd0f96395054",
}

DOMAIN_SYMBOLS = {
    "accounts": {
        "models": ("AccountsRequest", "BankStatementsRequest"),
        "services": ("get_accounts_data", "get_bank_statements_data"),
        "tools": ("get_accounts", "get_bank_statements"),
    },
    "budgets": {
        "models": ("BudgetProgressRequest",),
        "services": ("get_budget_progress_data",),
        "tools": ("get_budget_progress",),
    },
    "cash_flow": {
        "models": ("CashFlowRequest",),
        "services": ("get_cash_flow_data",),
        "tools": ("get_cash_flow",),
    },
    "debts": {
        "models": ("CompareDebtScenariosRequest", "DebtOverviewRequest"),
        "services": ("compare_debt_scenarios_data", "get_debt_overview_data"),
        "tools": ("compare_debt_scenarios", "get_debt_overview"),
    },
    "expenses": {
        "models": (
            "SpendingAnalysisRequest",
            "TransactionDisputesRequest",
            "TransactionsRequest",
        ),
        "services": (
            "analyze_spending_data",
            "get_transaction_disputes_data",
            "get_transactions_data",
        ),
        "tools": ("analyze_spending", "get_transaction_disputes", "get_transactions"),
    },
    "financial_health": {
        "models": ("FinancialAlertsRequest", "FinancialOverviewRequest"),
        "services": ("get_financial_alerts_data", "get_financial_overview_data"),
        "tools": ("get_financial_alerts", "get_financial_overview"),
    },
    "payments": {
        "models": ("BeneficiariesRequest", "PaymentActivityRequest", "UpcomingPaymentsRequest"),
        "services": (
            "get_beneficiaries_data",
            "get_payment_activity_data",
            "get_upcoming_payments_data",
        ),
        "tools": ("get_beneficiaries", "get_payment_activity", "get_upcoming_payments"),
    },
    "savings": {
        "models": ("SavingsProgressRequest",),
        "services": ("get_savings_progress_data",),
        "tools": ("get_savings_progress",),
    },
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
        listed_tools = await client.list_tools()
    listed = {tool.name: tool for tool in listed_tools}
    assert {tool.__name__ for tool in FINANCIAL_TOOLS} == FINANCIAL_NAMES
    assert FINANCIAL_NAMES <= listed.keys()
    assert len(FINANCIAL_TOOLS) == len(FINANCIAL_NAMES)
    assert all([tool.name for tool in listed_tools].count(name) == 1 for name in FINANCIAL_NAMES)
    for name in FINANCIAL_NAMES:
        description = listed[name].description or ""
        assert "/" in description
        assert "request" in listed[name].input_schema["properties"]
        request_schema = listed[name].input_schema["properties"]["request"]
        assert "scope" in request_schema["properties"]
        assert listed[name].annotations is not None
        assert listed[name].annotations.read_only_hint is True


@pytest.mark.asyncio
async def test_financial_tool_public_contracts_match_the_refactor_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SUPABASE_DATABASE_URL",
        "postgresql://reader:password@localhost/postgres?sslmode=require",
    )
    monkeypatch.setenv("MCP_ALLOWED_TABLES", "")
    async with Client(mcp) as client:
        listed = {tool.name: tool for tool in await client.list_tools()}
    actual = {}
    for name in FINANCIAL_NAMES:
        tool = listed[name]
        payload = json.dumps(
            {
                "description": tool.description,
                "output_schema": tool.output_schema,
                "parameters": tool.input_schema,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        actual[name] = hashlib.sha256(payload).hexdigest()
    assert actual == FINANCIAL_CONTRACT_HASHES


def test_new_domain_imports_and_compatibility_facades_resolve_to_same_symbols() -> None:
    layer_paths = {
        "models": "supabase_mcp.finance_models",
        "services": "supabase_mcp.services.finance",
        "tools": "supabase_mcp.tools.finance",
    }
    for domain, layers in DOMAIN_SYMBOLS.items():
        for layer, symbols in layers.items():
            legacy_module = importlib.import_module(layer_paths[layer])
            domain_module = importlib.import_module(f"{layer_paths[layer]}.{domain}")
            for symbol in symbols:
                assert getattr(legacy_module, symbol) is getattr(domain_module, symbol)


def test_wheel_contains_every_financial_domain_package(tmp_path: Path) -> None:
    wheel_name = build_wheel(str(tmp_path))
    with zipfile.ZipFile(tmp_path / wheel_name) as wheel:
        packaged = set(wheel.namelist())
        installed_path = tmp_path / "installed"
        wheel.extractall(installed_path)
    for layer in ("finance_models", "services/finance", "tools/finance"):
        assert f"supabase_mcp/{layer}/__init__.py" in packaged
        for domain in DOMAIN_SYMBOLS:
            assert f"supabase_mcp/{layer}/{domain}.py" in packaged

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(installed_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "import supabase_mcp; "
                "from supabase_mcp.server import mcp; "
                "package = Path(supabase_mcp.__file__).resolve(); "
                "assert package.is_relative_to(Path.cwd() / 'installed'); "
                "print(type(mcp).__name__)"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "FastMCP"


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
    assert (
        resolve_period("last_6_months", timezone_name="America/Monterrey", today=date(2026, 9, 12))[
            "start_date"
        ]
        == "2026-04-01"
    )


def test_custom_period_and_limits_are_strict() -> None:
    with pytest.raises(ValidationError):
        TransactionsRequest.model_validate({"scope": {"user_id": USER_A}, "period": "custom"})
    with pytest.raises(ValidationError):
        TransactionsRequest.model_validate({"scope": {"user_id": USER_A}, "limit": 101})
    request = TransactionsRequest.model_validate(
        {
            "scope": {"user_id": USER_A},
            "period": "custom",
            "start_date": "2026-09-01",
            "end_date": "2026-09-12",
        }
    )
    assert request.start_date == date(2026, 9, 1)
