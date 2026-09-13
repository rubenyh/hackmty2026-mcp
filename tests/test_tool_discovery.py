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
    _domain_terms,
    app_only,
)
from supabase_mcp.server import mcp

DISCOVERY_TOOLS = {SEARCH_TOOL_NAME, CALL_TOOL_NAME}

#: Registered but deliberately not discoverable: application/schema helpers
#: and the surfaces the orchestrator drives.
APP_ONLY_TOOLS = {
    "a2ui_form",
    "get_user_context",
    "list_allowed_tables",
    "describe_table",
    "present_financial_view",
    "chat_message",
    "a2ui_action",
    "a2ui_error",
}

REMOVED_TOOLS = {"select_rows", "health_check"}

FINANCIAL_TOOLS = {
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
    ("how is my budget doing?", "get_budget_progress"),
    ("como va mi presupuesto", "get_budget_progress"),
    ("show my cash flow", "get_cash_flow"),
    ("flujo de efectivo mensual", "get_cash_flow"),
    ("savings progress", "get_savings_progress"),
    ("what payments are coming up", "get_upcoming_payments"),
    ("proximos pagos", "get_upcoming_payments"),
    ("cuanto dinero tengo en mis cuentas", "get_accounts"),
    ("muestrame mi tarjeta de credito", "get_credit_cards"),
    ("I don't recognize this charge", "get_transaction_disputes"),
    ("quiero una aclaracion", "get_transaction_disputes"),
    ("compare payoff strategies for my debt", "compare_debt_scenarios"),
    ("send me my bank statement", "get_bank_statements"),
    ("beneficiarios guardados", "get_beneficiaries"),
    ("transfers I made last month", "get_payment_activity"),
    ("any alerts I should know about", "get_financial_alerts"),
    ("how are my finances overall", "get_financial_overview"),
    # English phrasings that do not repeat the metadata verbatim. The catalog is
    # English now, so these have to work without the Spanish text that used to
    # sit beside it.
    ("which payoff strategy costs the least interest", "compare_debt_scenarios"),
    ("saved payees I usually send money to", "get_beneficiaries"),
    ("am I close to my budget limit", "get_budget_progress"),
    ("money available in my accounts right now", "get_accounts"),
    ("unrecognized charge on my card", "get_transaction_disputes"),
    ("statement document for last month", "get_bank_statements"),
    ("did my transfer go through", "get_payment_activity"),
    ("what do I have to pay next week", "get_upcoming_payments"),
    ("is there anything I should worry about", "get_financial_alerts"),
    ("overall financial health", "get_financial_overview"),
    ("income versus expenses trend", "get_cash_flow"),
    ("my latest purchases", "get_transactions"),
    ("how much did I spend on groceries", "analyze_spending"),
    # The four model-backed predictions, in both product languages. Spanish
    # reaches an English-only catalog through the query lexicon alone.
    ("forecast my future cash balance", "forecast_cash_balance"),
    ("pronostica mi saldo y liquidez futura", "forecast_cash_balance"),
    ("cuando completare mi meta de ahorro", "predict_savings_goal"),
    ("predict my recurring subscription charges", "forecast_recurring_charges"),
    ("que cargos recurrentes vienen", "forecast_recurring_charges"),
    ("detect unusual transactions", "detect_transaction_anomalies"),
    ("encuentra movimientos anomalos", "detect_transaction_anomalies"),
]

#: Queries whose answer has a legitimate near-sibling in the catalog: a
#: historical tool and the predictive tool over the same entity. BM25 is
#: lexical, so it cannot tell "how is my goal going" (today) from "will I
#: complete it on time" (a projection) - both sentences carry the same domain
#: nouns. Ranking these by hand would mean writing metadata to game the index,
#: which is exactly what the descriptions must not do.
#:
#: The architecture does not need rank 1. `search_tools` returns several ranked
#: candidates and the model evaluates them, so what has to hold is that BOTH
#: siblings are offered and the model gets to choose. That is what is asserted.
SIBLING_INTENTS = [
    ("mis ultimos movimientos", "get_transactions", "detect_transaction_anomalies"),
    ("como va mi meta de ahorro", "get_savings_progress", "predict_savings_goal"),
    ("how is my savings goal going", "get_savings_progress", "predict_savings_goal"),
    ("will I complete my savings goal on time", "predict_savings_goal", "get_savings_progress"),
]

#: Spanish vocabulary must not reappear in the catalog the model reads. Model
#: metadata is English; the Spanish query is translated on the way in.
SPANISH_MARKERS = (
    "claves",
    "herramienta",
    "cuenta",
    "cuentas",
    "saldo",
    "tarjetas",
    "gastos",
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
    "datos",
    "para",
)


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
    assert REMOVED_TOOLS.isdisjoint(tool.name for tool in registered)
    assert REMOVED_TOOLS.isdisjoint(listed)


@pytest.mark.parametrize(("query", "expected"), DISCOVERY_INTENTS)
async def test_financial_intent_ranks_its_tool_first(query: str, expected: str) -> None:
    """An unambiguous intent puts its own tool at the top of the ranking."""
    async with Client(mcp) as client:
        names = await _search(client, query)

    assert names, f"no tool matched {query!r}"
    assert names[0] == expected, f"{query!r} ranked {names} instead of {expected}"
    assert len(names) <= SEARCH_MAX_RESULTS


@pytest.mark.parametrize(("query", "expected", "sibling"), SIBLING_INTENTS)
async def test_both_siblings_are_offered_so_the_model_can_choose(
    query: str, expected: str, sibling: str
) -> None:
    """A historical/predictive pair is handed to the model, not decided for it.

    Asserting rank 1 here would push the metadata toward keyword gaming for a
    distinction BM25 cannot make. The requirement the agent actually relies on
    is that the right tool is among the candidates it evaluates, and that its
    sibling is there too so the choice is the model's.
    """
    async with Client(mcp) as client:
        names = await _search(client, query)

    assert expected in names, f"{query!r} never offered {expected}: {names}"
    assert sibling in names, f"{query!r} never offered the sibling {sibling}: {names}"
    assert len(names) <= SEARCH_MAX_RESULTS


async def test_every_model_visible_tool_advertises_english_metadata() -> None:
    """The catalog BM25 indexes is the catalog the model reads, so it is English."""
    registered = await mcp._list_tools()
    visible = [tool for tool in registered if is_model_visible(tool)]

    assert {tool.name for tool in visible} == FINANCIAL_TOOLS | {
        "database_overview",
        "visualize_allowed_data",
    }
    for tool in visible:
        listed = tool.to_mcp_tool()
        title = listed.annotations.title if listed.annotations else None
        for label, text in (("description", listed.description), ("title", title)):
            if label == "description":
                assert text, f"{tool.name} has no description"
            if not text:
                continue
            assert text.isascii(), f"{tool.name} {label} is not ASCII English: {text!r}"
            assert "Claves" not in text, f"{tool.name} {label} still carries a keyword list"
            assert " / " not in text, f"{tool.name} {label} still looks bilingual"
            words = {word.strip(".,;:()").casefold() for word in text.split()}
            assert not words.intersection(SPANISH_MARKERS), (
                f"{tool.name} {label} carries Spanish words: {text!r}"
            )


def test_spanish_query_is_translated_into_the_english_catalog() -> None:
    """Stopwords are dropped and domain words are expressed in catalog English."""
    assert _domain_terms("cuanto gaste este mes") == "spent month"
    assert _domain_terms("muestra mis deudas pendientes") == "muestra debts outstanding"
    assert _domain_terms("¿cuál es mi flujo de efectivo?") == "cash flow"
    # An English query is left alone apart from its function words.
    assert _domain_terms("how much did I spend this month") == "spend month"
    # A degenerate query still behaves exactly as it does upstream.
    assert _domain_terms("de la que") == "de la que"


#: The four model-backed predictions, asked the way the product's users ask.
#: Their descriptions are English-only, so every one of these has to reach its
#: tool through the query lexicon rather than through matching Spanish text.
SPANISH_PREDICTIVE_INTENTS = [
    ("pronostico de mi saldo futuro", "forecast_cash_balance"),
    ("como va mi liquidez en los proximos dias", "forecast_cash_balance"),
    ("probabilidad de completar mi meta de ahorro", "predict_savings_goal"),
    ("fecha estimada para terminar mi ahorro", "predict_savings_goal"),
    ("cargos recurrentes que vienen", "forecast_recurring_charges"),
    ("prediccion de mis suscripciones", "forecast_recurring_charges"),
    ("detecta movimientos inusuales", "detect_transaction_anomalies"),
    ("tengo alguna anomalia en mis movimientos", "detect_transaction_anomalies"),
]


@pytest.mark.parametrize(("query", "expected"), SPANISH_PREDICTIVE_INTENTS)
async def test_spanish_query_still_reaches_each_predictive_tool(
    query: str, expected: str
) -> None:
    """The catalog stayed English; Spanish retrieval rides on the query lexicon."""
    async with Client(mcp) as client:
        names = await _search(client, query)

    assert expected in names, f"{query!r} returned {names}"


async def test_search_never_returns_infrastructure_or_presentation_tools() -> None:
    async with Client(mcp) as client:
        for query, _ in DISCOVERY_INTENTS + [(q, e) for q, e, _ in SIBLING_INTENTS]:
            names = await _search(client, query)
            assert APP_ONLY_TOOLS.isdisjoint(names), f"{query!r} surfaced {names}"


async def test_removed_tools_cannot_be_searched_or_called() -> None:
    async with Client(mcp) as client:
        for name in REMOVED_TOOLS:
            assert name not in await _search(client, name.replace("_", " "))
            with pytest.raises(ToolError):
                await client.call_tool(name, {}, raise_on_error=True)
            with pytest.raises(ToolError):
                await client.call_tool(
                    "call_tool", {"name": name, "arguments": {}}, raise_on_error=True
                )


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
#: `get_user_context` builds the user context on every turn; `a2ui_action` and
#: `a2ui_form` carry the confirmed-action flow; `database_overview` backs an
#: explicit API route.
ORCHESTRATOR_DRIVEN_TOOLS = {
    "get_user_context",
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
