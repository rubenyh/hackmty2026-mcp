"""Offline contract tests for the nineteen financial domain tools."""

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
    "detect_transaction_anomalies",
    "forecast_cash_balance",
    "forecast_recurring_charges",
    "predict_savings_goal",
}
# Baseline regenerated for progressive tool discovery: every financial
# description was rewritten for BM25 retrieval and mutual disambiguation, and
# ambiguous parameters gained Field descriptions. Names, request shapes and
# structured results are unchanged — only the discovery text moved, which is
# exactly what this guard is meant to make visible rather than silent.
FINANCIAL_CONTRACT_HASHES = {
    "analyze_spending": "1831adbc017e558d61a5c9b9df3f6e01bd1545b7b8c23b460379c83206809eeb",
    "compare_debt_scenarios": "14fd880407b9457be41e7d4ff5ae504c5b5bac967e4c35b18874469f364ae27a",
    "detect_transaction_anomalies": (
        "7ea9b304892e09539d62c307c9d90f7b1e3657b43a9d882c824760d64db200a8"
    ),
    "forecast_cash_balance": "0198db0bda9157dd09622f80018f641db5da358a057686490fdee3b89da3c2f9",
    "forecast_recurring_charges": (
        "bfd1e2ba041ef75f125968ca65e7ac5470f0f40d60923f0155c212483bc60632"
    ),
    "get_accounts": "ce178365d0c716666cb03d9d530e9f062019e540a96a3c3a38e855c6dcf2982d",
    "get_bank_statements": "ac188c111c49e85b0098267058ee4a3184dec52684d5f1b15ced999d985dbfd1",
    "get_beneficiaries": "fea659d07a9c068f6d85dd35ae94787e59516313649b28799a87abc51dc67521",
    "get_budget_progress": "348f61f4d69e0aabcfb121e5e28267976fd4185a8deaf53eb20b018884d06a1f",
    "get_cash_flow": "71d506b99fc8373d29e27ea4e4e0a8e6a84ca5bfc484a8ea19d08281d7d45c30",
    "get_debt_overview": "7d56a6d907f71b91e6322f9ea37d4fdce00c80b372adad9d0f441c85379af3a9",
    "get_financial_alerts": "1753d53775caba85da553b6765aa2cd9adee12d9569860c67553d670bf68d72b",
    "get_financial_overview": "2799811cd8f34c513b4c46125fc77c97dc8779ec6d9bedd9fde6f9995bae0150",
    "get_payment_activity": "bb459709075efe608d599aa55f181097eb22a571be8a324868cabb27a8243f34",
    "get_savings_progress": "4282c2ec1080fad55b0422bf4177b94ad8ee4e08ad93da63b0c73a396e92208a",
    "get_transaction_disputes": "767a52ca9ee5257b7ec0769bedac64987896eaf0df6f224bc89a4895ad568a70",
    "get_transactions": "c232bd780f38780d4568bf51bbca7970f9f52202ad9b643568198c0ea12876cc",
    "get_upcoming_payments": "f3a8cac17d944eef1e24a87ed6a496615f0196e89cd46fd3d87124cac42d6fc5",
    "predict_savings_goal": "1f4cfeb9ec3c77819bf3ac5be1093ee14e77c419974a78fe657d67a56fbd4c43",
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
    "predictions": {
        "models": (
            "DetectTransactionAnomaliesRequest",
            "ForecastCashBalanceRequest",
            "ForecastRecurringChargesRequest",
            "PredictSavingsGoalRequest",
        ),
        "services": ("PredictionService",),
        "tools": (
            "detect_transaction_anomalies",
            "forecast_cash_balance",
            "forecast_recurring_charges",
            "predict_savings_goal",
        ),
    },
    "savings": {
        "models": ("SavingsProgressRequest",),
        "services": ("get_savings_progress_data",),
        "tools": ("get_savings_progress",),
    },
}


@pytest.mark.asyncio
async def test_all_nineteen_tools_are_registered_with_bilingual_discovery_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SUPABASE_DATABASE_URL",
        "postgresql://reader:password@localhost/postgres?sslmode=require",
    )
    monkeypatch.setenv("MCP_ALLOWED_TABLES", "")
    # Progressive discovery replaces `tools/list` with the search pair, so the
    # contract these tools must satisfy is checked on the registered catalog —
    # the definitions `search_tools` actually hands back.
    listed_tools = [tool.to_mcp_tool() for tool in await mcp._list_tools()]
    listed = {tool.name: tool for tool in listed_tools}
    async with Client(mcp) as client:
        advertised = {tool.name for tool in await client.list_tools()}
    # Discovery pair plus the tools pinned purely so the host can address them.
    assert {"search_tools", "call_tool"} <= advertised
    assert FINANCIAL_NAMES.isdisjoint(advertised)
    assert {tool.__name__ for tool in FINANCIAL_TOOLS} == FINANCIAL_NAMES
    assert FINANCIAL_NAMES <= listed.keys()
    assert len(FINANCIAL_TOOLS) == len(FINANCIAL_NAMES)
    assert all([tool.name for tool in listed_tools].count(name) == 1 for name in FINANCIAL_NAMES)
    for name in FINANCIAL_NAMES:
        description = listed[name].description or ""
        assert "/" in description
        schema = listed[name].input_schema
        assert "request" in schema["properties"]
        request_schema = schema["properties"]["request"]
        reference = request_schema.get("$ref")
        if reference is not None:
            request_schema = schema["$defs"][reference.rsplit("/", 1)[-1]]
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
    listed = {tool.name: tool.to_mcp_tool() for tool in await mcp._list_tools()}
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
