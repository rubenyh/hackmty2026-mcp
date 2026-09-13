"""Offline contract tests for the twenty financial domain tools."""

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
    "get_credit_cards",
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
# Baseline regenerated for the English metadata pass over the merged catalog:
# every financial description, display title and parameter description is
# English, the `Claves:` keyword lists are gone, and the five new tools
# (`get_credit_cards` plus the four model-backed predictions) joined the set.
# Names, request shapes and structured results are unchanged — only the
# model-facing text moved, which is exactly what this guard makes visible
# rather than silent.
FINANCIAL_CONTRACT_HASHES: dict[str, str] = {
    "analyze_spending": "3b364a1a15f09a5ebfb7fef419d318a5b19a9694510b7c41a62830408e0bc541",
    "compare_debt_scenarios": "5460ee9bcb1ddbe79ea25d55f025be4459f49cadda38ff981a1bd787aa62b23a",
    "detect_transaction_anomalies": (
        "7891bb7c392af1c1c6ddbd46fb388597d143a672117d55cc9cea498e7c6d790a"
    ),
    "forecast_cash_balance": "c3eef211865f8b41e4c362af40f072c360d46927ac02098aefa1591804b81627",
    "forecast_recurring_charges": (
        "21565cb3ab3f74cf1315a978360c379690a234b1ee11eec5b915890f6a9d9db6"
    ),
    "get_accounts": "f2d1e05dffd55cf5c56c370357739ed647ebf383cbb4b6947198e864482ae2c4",
    "get_bank_statements": "9e08492e2abf6d47ada0bb8dc287663cafe113b8467533b60f74eff53ca99a2d",
    "get_beneficiaries": "1fcb897bfef2b6b4bf579443340d3e19b9a7bc6aee96c8c05e7670e222681cf0",
    "get_budget_progress": "d6478cd05d77441d77711e82c2398e874a3c460c9e4bda7d000478571d00ee33",
    "get_cash_flow": "c49ace07aebae74e699870b2a5b77ae17472ef5b1418da553266c795945d9d71",
    "get_credit_cards": "5a6cf94f6b1cf0a309fb8d339adb4ee881c740b622fe3d3ed5793fc1939dbbd0",
    "get_debt_overview": "bcba3b53230cbde9eb6fc2c2561a80196025a0d43a9c568abd8a029c48908d8a",
    "get_financial_alerts": "60264d2f6f50a4e3cb48013c0abf829e590f900a1936c94eba65a2ec69e1e737",
    "get_financial_overview": "f2edcecfdef260c8613966191c451792cdba45677e8e0ac67e881d9323038e81",
    "get_payment_activity": "8d2e7d72a92ae9af2f346d940b7e2817d49a7bd4f593f2a989f7ba3d38f0bd29",
    "get_savings_progress": "ee84f89e64c379a69ab13def0be0054ead9084dd81c0e43ca9fdd45c263c9842",
    "get_transaction_disputes": "39663c44a20bf9ec2971e85957ab4fbbc970379ca7a28c1c2b2d36bd48a54516",
    "get_transactions": "de1b8f4ba980c7028f060e8cf0cf10b8c1b46d8cc17fbf748f73366cda4455f1",
    "get_upcoming_payments": "8ba1e34777afb48cf0d2a86ed485ca5f853d2a56229cf26513c28cf7429fdf5c",
    "predict_savings_goal": "640c8c11cfa3c4ec4e774c9d482def71874e37160f0660a2e7df90a070e824bf",
}

#: The whole permitted domain/capability vocabulary. `predictive` is project
#: taxonomy for forward projection, not an MCP protocol hint.
DOMAIN_TAGS = {
    "accounts",
    "transactions",
    "expenses",
    "cash-flow",
    "budgets",
    "savings",
    "debts",
    "analytics",
    "predictive",
    "actions",
}

#: Non-domain plumbing: the application turn-context loader, schema primitives
#: and A2UI presentation. These are not banking capabilities and keep their own
#: tags.
PLUMBING_TAGS = {"a2ui", "actions", "application", "charts", "context", "schema"}

#: The exact set whose payload is forward-looking. `compare_debt_scenarios`
#: projects months to payoff and total interest under stored assumptions; the
#: other four call the models service and return a forecast, a completion
#: probability or an anomaly score. Every other financial tool reports recorded
#: state, and `analyze_spending`'s prior-period comparison is history, not a
#: forecast.
PREDICTIVE_TOOLS = {
    "compare_debt_scenarios",
    "forecast_cash_balance",
    "predict_savings_goal",
    "forecast_recurring_charges",
    "detect_transaction_anomalies",
}

#: Spanish vocabulary that must not reappear in model-facing metadata. The
#: catalog is read by the model in English; the Spanish user query is translated
#: on the way into tool search instead (see `supabase_mcp.discovery`).
SPANISH_MARKERS = (
    "claves",
    "herramienta",
    "cuenta",
    "cuentas",
    "saldo",
    "tarjeta",
    "gasto",
    "gastos",
    "deuda",
    "deudas",
    "presupuesto",
    "ahorro",
    "pagos",
    "movimientos",
    "aclaracion",
    "beneficiarios",
    "financiera",
    "esquema",
    "grafica",
    "ambito",
    "datos",
    "para",
)


def _assert_english(text: str, where: str) -> None:
    """Model-facing metadata must be English prose, not bilingual keyword text."""
    assert text, f"{where} is empty"
    assert text.isascii(), f"{where} carries non-ASCII text: {text!r}"
    assert "Claves" not in text, f"{where} still carries a keyword list"
    assert " / " not in text, f"{where} still looks bilingual"
    words = {word.strip(".,;:()").casefold() for word in text.split()}
    offenders = words.intersection(SPANISH_MARKERS)
    assert not offenders, f"{where} carries Spanish words {sorted(offenders)}"


DOMAIN_SYMBOLS = {
    "accounts": {
        "models": ("AccountsRequest", "BankStatementsRequest", "CreditCardsRequest"),
        "services": (
            "get_accounts_data",
            "get_bank_statements_data",
            "get_credit_cards_data",
        ),
        "tools": ("get_accounts", "get_bank_statements", "get_credit_cards"),
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
async def test_all_twenty_tools_are_registered_with_english_discovery_text(
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
        _assert_english(description, f"{name} description")
        # What it does, what it returns, and how it differs from its neighbours.
        assert "Returns" in description, f"{name} never says what it returns"
        assert "Use it" in description, f"{name} never says when to use it"
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
async def test_every_financial_parameter_description_is_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parameter text lives on the Pydantic request models, and is read by the model."""
    monkeypatch.setenv(
        "SUPABASE_DATABASE_URL",
        "postgresql://reader:password@localhost/postgres?sslmode=require",
    )
    monkeypatch.setenv("MCP_ALLOWED_TABLES", "")
    listed = {tool.name: tool.to_mcp_tool() for tool in await mcp._list_tools()}
    for name in FINANCIAL_NAMES:
        schema = listed[name].input_schema
        for definition in schema.get("$defs", {}).values():
            for field, info in definition.get("properties", {}).items():
                description = info.get("description")
                if description:
                    _assert_english(description, f"{name}.{field} description")


@pytest.mark.asyncio
async def test_model_visible_titles_and_tags_follow_the_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SUPABASE_DATABASE_URL",
        "postgresql://reader:password@localhost/postgres?sslmode=require",
    )
    monkeypatch.setenv("MCP_ALLOWED_TABLES", "")
    registered = await mcp._list_tools()
    predictive = set()
    for tool in registered:
        assert tool.tags <= DOMAIN_TAGS | PLUMBING_TAGS, f"{tool.name} has tags {tool.tags}"
        if "predictive" in tool.tags:
            predictive.add(tool.name)
        if tool.name in FINANCIAL_NAMES:
            # A financial capability is described only in domain vocabulary.
            assert tool.tags <= DOMAIN_TAGS, f"{tool.name} has non-domain tags {tool.tags}"
            assert tool.tags, f"{tool.name} has no domain tag"
        listed = tool.to_mcp_tool()
        if listed.annotations is not None and listed.annotations.title:
            _assert_english(listed.annotations.title, f"{tool.name} title")
    assert predictive == PREDICTIVE_TOOLS


@pytest.mark.asyncio
async def test_tool_annotations_match_what_the_tools_actually_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SUPABASE_DATABASE_URL",
        "postgresql://reader:password@localhost/postgres?sslmode=require",
    )
    monkeypatch.setenv("MCP_ALLOWED_TABLES", "")
    listed = {tool.name: tool.to_mcp_tool() for tool in await mcp._list_tools()}
    for name in FINANCIAL_NAMES | {"database_overview", "visualize_allowed_data"}:
        annotations = listed[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is True, f"{name} claims to write"
        assert annotations.destructive_hint is False
        assert annotations.idempotent_hint is True
        assert annotations.open_world_hint is False, f"{name} reads one allowlisted database"
    # `a2ui_action` is the one write boundary. Repeating the exact same A2UI
    # event is a no-op because `apply_a2ui_action` keeps a receipt per
    # (user, request_key), but `budget.update` and `savings_goal.update`
    # overwrite the fields of an existing row, which is a destructive update.
    action = listed["a2ui_action"].annotations
    assert action is not None
    assert action.read_only_hint is False
    assert action.destructive_hint is True
    assert action.idempotent_hint is True
    assert action.open_world_hint is False


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
