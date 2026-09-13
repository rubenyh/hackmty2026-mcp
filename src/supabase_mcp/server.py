"""FastMCP server construction and executable entry point."""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging
from collections.abc import AsyncIterator, Callable
from importlib.resources import files
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan
from mcp.types import ToolAnnotations

from supabase_mcp.a2ui_support.constants import A2UI_MIME_TYPE
from supabase_mcp.a2ui_support.models import SurfaceSpec
from supabase_mcp.a2ui_support.response import ui_metadata
from supabase_mcp.a2ui_support.surfaces import (
    ACTION_SURFACES,
    CHAT_MESSAGE_SURFACE,
    DATA_CHART_SURFACE,
    DATABASE_OVERVIEW_SURFACE,
    FINANCIAL_VIEW_SURFACE,
    SURFACE_REGISTRY,
)
from supabase_mcp.config import Settings
from supabase_mcp.database import DatabaseClient
from supabase_mcp.discovery import (
    DiscoveryLoggingMiddleware,
    app_only,
    build_tool_search_transform,
)
from supabase_mcp.inference import InferenceClient
from supabase_mcp.services.finance.predictions import PredictionService
from supabase_mcp.tools import (
    FINANCIAL_TOOLS,
    a2ui_action,
    a2ui_error,
    chat_message,
    chat_message_resource,
    data_chart_resource,
    database_overview,
    database_overview_resource,
    describe_table,
    financial_view_resource,
    health_check,
    list_allowed_tables,
    present_financial_view,
    select_rows,
    visualize_allowed_data,
)
from supabase_mcp.tools.action_forms import a2ui_form
from supabase_mcp.tools.finance import FINANCIAL_REQUEST_MODELS
from supabase_mcp.tools.finance._shared import FinancialValidationMiddleware


def load_settings() -> Settings:
    """Load environment-backed settings (Pydantic's generated signature appears required)."""
    return Settings()  # type: ignore[call-arg]


@lifespan
async def app_lifespan(_server: FastMCP[Any]) -> AsyncIterator[dict[str, Any]]:
    """Create and dispose the process-scoped database and inference clients."""
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    database = DatabaseClient(settings)
    inference = InferenceClient(settings)
    await database.start()
    try:
        await inference.start()
        try:
            yield {
                "database": database,
                "inference": inference,
                "predictions": PredictionService(database, inference),
            }
        finally:
            await inference.stop()
    finally:
        await database.stop()


mcp = FastMCP("Supabase Read-Only", lifespan=app_lifespan)
mcp.tool(
    a2ui_form,
    tags={"a2ui", "actions"},
    meta=app_only(),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False),
)


def action_resource_reader(surface: SurfaceSpec) -> Callable[[], str]:
    def read() -> str:
        return SURFACE_REGISTRY.serialized_template(surface)

    return read


for action_name, action_surface in ACTION_SURFACES.items():
    mcp.resource(
        action_surface.resource_uri, name=action_name.replace(".", "_"), mime_type=A2UI_MIME_TYPE
    )(action_resource_reader(action_surface))


def input_contract_resource() -> str:
    return files("supabase_mcp.a2ui_actions").joinpath("inputs.json").read_text()


def action_contract_resource() -> str:
    return files("supabase_mcp.a2ui_actions").joinpath("actions.json").read_text()


mcp.resource("a2ui://actions/inputs", mime_type="application/json")(input_contract_resource)
mcp.resource("a2ui://actions/registry", mime_type="application/json")(action_contract_resource)
mcp.add_middleware(FinancialValidationMiddleware(FINANCIAL_REQUEST_MODELS))
#: Domain tags per financial tool. FastMCP stores them on the component for
#: filtering and operator tooling; BM25 indexes names, descriptions and
#: parameters, so retrieval quality lives in the docstrings, not here.
FINANCIAL_TOOL_TAGS: dict[str, set[str]] = {
    "get_financial_overview": {"finance", "accounts", "budgets", "savings", "debts"},
    "get_accounts": {"finance", "accounts", "credit"},
    "get_credit_cards": {"finance", "accounts", "credit", "cards"},
    "get_transactions": {"finance", "transactions", "expenses"},
    "analyze_spending": {"finance", "expenses", "transactions"},
    "get_cash_flow": {"finance", "cash-flow"},
    "get_budget_progress": {"finance", "budgets", "expenses"},
    "get_savings_progress": {"finance", "savings"},
    "get_debt_overview": {"finance", "debts", "credit"},
    "get_upcoming_payments": {"finance", "cash-flow", "debts"},
    "get_financial_alerts": {"finance", "budgets", "accounts"},
    "get_bank_statements": {"finance", "accounts"},
    "get_payment_activity": {"finance", "transactions", "accounts"},
    "get_beneficiaries": {"finance", "accounts"},
    "get_transaction_disputes": {"finance", "transactions", "credit"},
    "compare_debt_scenarios": {"finance", "debts", "credit"},
    "forecast_cash_balance": {"finance", "predictions", "cash-flow", "liquidity"},
    "predict_savings_goal": {"finance", "predictions", "savings"},
    "forecast_recurring_charges": {"finance", "predictions", "transactions"},
    "detect_transaction_anomalies": {"finance", "predictions", "transactions", "security"},
}

# Infrastructure and generic schema primitives. They stay registered and stay
# callable by the trusted orchestrator, but they are declared host/app-only so
# tool search and the `call_tool` proxy never hand them to a model: readiness
# checks and a generic row reader are not banking capabilities, and letting
# discovery surface them would widen model reach rather than narrow context.
mcp.tool(health_check, tags={"infrastructure"}, meta=app_only())
mcp.tool(list_allowed_tables, tags={"schema"}, meta=app_only())
mcp.tool(describe_table, tags={"schema"}, meta=app_only())
mcp.tool(select_rows, tags={"schema"}, meta=app_only())
for financial_tool in FINANCIAL_TOOLS:
    mcp.tool(
        financial_tool,
        tags=FINANCIAL_TOOL_TAGS[financial_tool.__name__],
        annotations=ToolAnnotations(
            title=f"{financial_tool.__name__.replace('_', ' ').title()} / Herramienta financiera",
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
mcp.tool(
    database_overview,
    tags={"schema", "a2ui"},
    meta=ui_metadata(DATABASE_OVERVIEW_SURFACE),
    annotations=ToolAnnotations(
        title="Database overview",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
mcp.tool(
    visualize_allowed_data,
    tags={"a2ui", "charts", "finance"},
    meta=ui_metadata(DATA_CHART_SURFACE),
    annotations=ToolAnnotations(
        title="Visualize allowed data",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
mcp.tool(
    present_financial_view,
    tags={"a2ui"},
    meta=app_only(ui_metadata(FINANCIAL_VIEW_SURFACE)),
    annotations=ToolAnnotations(
        title="Present financial view",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
mcp.tool(
    chat_message,
    tags={"a2ui"},
    meta=app_only(ui_metadata(CHAT_MESSAGE_SURFACE)),
    annotations=ToolAnnotations(
        title="Present chat message",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
mcp.tool(
    a2ui_action,
    tags={"a2ui", "actions"},
    meta=app_only(),
    annotations=ToolAnnotations(
        title="Handle user-confirmed A2UI action",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
mcp.tool(
    a2ui_error,
    tags={"a2ui", "actions"},
    meta=app_only(),
    annotations=ToolAnnotations(
        title="Report A2UI client error",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
mcp.resource(
    DATABASE_OVERVIEW_SURFACE.resource_uri,
    name="database_overview_a2ui",
    title=DATABASE_OVERVIEW_SURFACE.title,
    description=DATABASE_OVERVIEW_SURFACE.description,
    mime_type=A2UI_MIME_TYPE,
)(database_overview_resource)
mcp.resource(
    DATA_CHART_SURFACE.resource_uri,
    name="data_chart_a2ui",
    title=DATA_CHART_SURFACE.title,
    description=DATA_CHART_SURFACE.description,
    mime_type=A2UI_MIME_TYPE,
)(data_chart_resource)
mcp.resource(
    CHAT_MESSAGE_SURFACE.resource_uri,
    name="chat_message_a2ui",
    title=CHAT_MESSAGE_SURFACE.title,
    description=CHAT_MESSAGE_SURFACE.description,
    mime_type=A2UI_MIME_TYPE,
)(chat_message_resource)
mcp.resource(
    FINANCIAL_VIEW_SURFACE.resource_uri,
    name="financial_view_a2ui",
    title=FINANCIAL_VIEW_SURFACE.title,
    description=FINANCIAL_VIEW_SURFACE.description,
    mime_type=A2UI_MIME_TYPE,
)(financial_view_resource)


# Progressive discovery is installed last so it transforms the complete
# catalog: `tools/list` collapses to `search_tools` + `call_tool`, while every
# tool above stays registered, individually specialized and callable.
mcp.add_middleware(DiscoveryLoggingMiddleware())
mcp.add_transform(build_tool_search_transform())


def main() -> None:
    """Run using environment-configured stdio or Streamable HTTP transport."""
    settings = load_settings()
    if settings.transport == "http":
        mcp.run(transport="http", host=settings.host, port=settings.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
