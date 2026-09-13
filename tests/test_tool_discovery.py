"""Offline tests for progressive tool discovery over the financial catalog."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client
from fastmcp.apps.config import is_model_visible
from fastmcp.exceptions import ToolError

from supabase_mcp.discovery import (
    ALWAYS_VISIBLE,
    CALL_TOOL_NAME,
    SEARCH_MAX_RESULTS,
    SEARCH_TOOL_NAME,
    app_only,
)
from supabase_mcp.server import mcp

DISCOVERY_TOOLS = {SEARCH_TOOL_NAME, CALL_TOOL_NAME}

#: Registered but deliberately not discoverable: infrastructure readiness, the
#: generic schema/row primitives, and the surfaces the orchestrator drives.
APP_ONLY_TOOLS = {
    "a2ui_form",
    "health_check",
    "list_allowed_tables",
    "describe_table",
    "select_rows",
    "present_financial_view",
    "chat_message",
    "a2ui_action",
    "a2ui_error",
}

FINANCIAL_TOOLS = {
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
    "forecast_cash_balance",
    "predict_savings_goal",
    "forecast_recurring_charges",
    "detect_transaction_anomalies",
}

#: One realistic user intent per financial capability, in both product
#: languages. The tool named here must rank first, not merely appear.
DISCOVERY_INTENTS = [
    ("show my outstanding debts", "get_debt_overview"),
    ("muestra mis deudas pendientes", "get_debt_overview"),
    ("how much did I spend this month?", "analyze_spending"),
    ("cuanto gaste este mes", "analyze_spending"),
    ("show my latest transactions", "get_transactions"),
    ("mis ultimos movimientos", "get_transactions"),
    ("how is my budget doing?", "get_budget_progress"),
    ("como va mi presupuesto", "get_budget_progress"),
    ("show my cash flow", "get_cash_flow"),
    ("flujo de efectivo mensual", "get_cash_flow"),
    ("savings progress", "get_savings_progress"),
    ("como va mi meta de ahorro", "get_savings_progress"),
    ("what payments are coming up", "get_upcoming_payments"),
    ("proximos pagos", "get_upcoming_payments"),
    ("cuanto dinero tengo en mis cuentas", "get_accounts"),
    ("I don't recognize this charge", "get_transaction_disputes"),
    ("quiero una aclaracion", "get_transaction_disputes"),
    ("compare payoff strategies for my debt", "compare_debt_scenarios"),
    ("send me my bank statement", "get_bank_statements"),
    ("beneficiarios guardados", "get_beneficiaries"),
    ("transfers I made last month", "get_payment_activity"),
    ("any alerts I should know about", "get_financial_alerts"),
    ("how are my finances overall", "get_financial_overview"),
    ("forecast my future cash balance", "forecast_cash_balance"),
    ("pronostica mi saldo y liquidez futura", "forecast_cash_balance"),
    ("will I complete my savings goal on time", "predict_savings_goal"),
    ("cuando completare mi meta de ahorro", "predict_savings_goal"),
    ("predict my recurring subscription charges", "forecast_recurring_charges"),
    ("que cargos recurrentes vienen", "forecast_recurring_charges"),
    ("detect unusual transactions", "detect_transaction_anomalies"),
    ("encuentra movimientos anomalos", "detect_transaction_anomalies"),
]


@pytest.fixture(autouse=True)
def _offline_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SUPABASE_DATABASE_URL",
        "postgresql://reader:password@localhost/postgres?sslmode=require",
    )
    monkeypatch.setenv("MCP_ALLOWED_TABLES", "")


async def _search(client: Client[Any], query: str) -> list[str]:
    result = await client.call_tool("search_tools", {"query": query})
    assert isinstance(result.data, list)
    return [definition["name"] for definition in result.data]


async def test_tools_list_is_only_the_discovery_pair() -> None:
    registered = await mcp._list_tools()
    async with Client(mcp) as client:
        listed = {tool.name for tool in await client.list_tools()}

    # The pinned tools are addressable by the host; the model-facing surface is
    # still just the discovery pair.
    assert listed == DISCOVERY_TOOLS | set(ALWAYS_VISIBLE)
    assert APP_ONLY_TOOLS.issuperset(ALWAYS_VISIBLE)
    # The catalog is an order of magnitude larger than what the model receives.
    assert len(registered) >= 25
    assert FINANCIAL_TOOLS <= {tool.name for tool in registered}


@pytest.mark.parametrize(("query", "expected"), DISCOVERY_INTENTS)
async def test_financial_intent_ranks_its_tool_first(query: str, expected: str) -> None:
    async with Client(mcp) as client:
        names = await _search(client, query)

    assert names, f"no tool matched {query!r}"
    assert names[0] == expected, f"{query!r} ranked {names} instead of {expected}"
    assert len(names) <= SEARCH_MAX_RESULTS


async def test_search_never_returns_infrastructure_or_presentation_tools() -> None:
    async with Client(mcp) as client:
        for query, _ in DISCOVERY_INTENTS:
            names = await _search(client, query)
            assert APP_ONLY_TOOLS.isdisjoint(names), f"{query!r} surfaced {names}"


async def test_search_results_carry_callable_schemas() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("search_tools", {"query": "muestra mis deudas"})
        definition = next(item for item in result.data if item["name"] == "get_debt_overview")

    assert definition["description"]
    request = definition["inputSchema"]["properties"]["request"]
    assert "scope" in request["properties"]


async def test_unmatched_query_returns_nothing_rather_than_noise() -> None:
    async with Client(mcp) as client:
        assert await _search(client, "zzzz qwertyuiop") == []


async def test_discovered_tool_executes_through_the_proxy_into_its_service() -> None:
    """search -> call_tool -> real domain tool, with the A2UI contract intact."""
    async with Client(mcp) as client:
        assert "database_overview" in await _search(client, "allowlisted tables and views")

        result = await client.call_tool(
            "call_tool", {"name": "database_overview", "arguments": {"limit": 5}}
        )

    assert result.is_error is not True
    assert result.structured_content is not None
    assert result.structured_content["ok"] is True
    # The proxy is a pass-through: the surface link the mobile client renders
    # from must survive discovery untouched.
    assert result.meta is not None
    assert result.meta["ui"]["resourceUri"] == "a2ui://database/overview"


async def test_proxy_preserves_domain_validation_and_scope_requirements() -> None:
    async with Client(mcp) as client:
        missing_scope = await client.call_tool(
            "call_tool",
            {"name": "get_transactions", "arguments": {"request": {}}},
            raise_on_error=False,
        )

    assert missing_scope.is_error is True


async def test_proxy_refuses_tools_the_model_may_not_discover() -> None:
    """Discovery must not become a second, unmediated way into hidden tools."""
    async with Client(mcp) as client:
        for name in APP_ONLY_TOOLS:
            with pytest.raises(ToolError):
                await client.call_tool(
                    "call_tool", {"name": name, "arguments": {}}, raise_on_error=True
                )


async def test_app_only_tools_remain_callable_by_the_trusted_orchestrator() -> None:
    """Hiding a tool from the model must not remove it from the server."""
    async with Client(mcp) as client:
        result = await client.call_tool("list_allowed_tables", {})

    assert result.structured_content is not None
    assert result.structured_content["ok"] is True


def test_app_only_preserves_existing_ui_metadata() -> None:
    merged = app_only({"ui": {"resourceUri": "a2ui://chat/message", "mimeType": "x"}})

    assert merged["ui"]["resourceUri"] == "a2ui://chat/message"
    assert merged["ui"]["mimeType"] == "x"
    assert merged["ui"]["visibility"] == ["app"]


#: Tools the trusted orchestrator addresses by name rather than discovering.
#: `select_rows` builds the user context on every turn; `a2ui_action` and
#: `a2ui_form` carry the confirmed-action flow; `database_overview` backs an
#: explicit API route.
ORCHESTRATOR_DRIVEN_TOOLS = {
    "select_rows",
    "a2ui_action",
    "a2ui_form",
    "database_overview",
}


async def test_every_orchestrator_driven_tool_is_still_reachable() -> None:
    """A tool that is neither advertised nor model-visible cannot be called.

    A hosted deployment fronts this server with a proxy that resolves
    `tools/call` against the advertised catalog, so an unadvertised tool answers
    `Unknown tool` by name and must go through `call_tool` — which in turn
    refuses anything declared app-only. App-only plus unpinned is therefore
    unreachable, and that combination silently broke user context in
    production. Each of these tools must keep exactly one open door.
    """
    registered = {tool.name: tool for tool in await mcp._list_tools()}
    async with Client(mcp) as client:
        advertised = {tool.name for tool in await client.list_tools()}

    for name in ORCHESTRATOR_DRIVEN_TOOLS:
        assert name in registered, f"{name} is not registered at all"
        pinned = name in advertised
        discoverable = is_model_visible(registered[name])
        assert pinned or discoverable, (
            f"{name} is app-only and unpinned: unreachable by name and refused by the proxy"
        )


async def test_pinning_widens_addressing_without_widening_the_model() -> None:
    """The pinned tools are on the list for the host, never for the model."""
    registered = {tool.name: tool for tool in await mcp._list_tools()}
    async with Client(mcp) as client:
        advertised = {tool.name for tool in await client.list_tools()}
        for name in ALWAYS_VISIBLE:
            assert name in advertised
            assert not is_model_visible(registered[name])
            # Search must not offer it, and the proxy must not execute it.
            assert name not in await _search(client, name.replace("_", " "))
            with pytest.raises(ToolError):
                await client.call_tool("call_tool", {"name": name, "arguments": {}})
